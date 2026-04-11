import { Command } from "commander";
import { AdbClient, AndroidClient } from "../../adapters/android/index.js";
import { parsePositiveInt } from "../validate.js";
import { acquireApk, FdroidProvider } from "../../core/apk/index.js";
import { ArtifactWriter } from "../../core/artifacts/index.js";
import { detectPatterns } from "../../core/patterns/index.js";
import type { Artifacts } from "../../core/schema/index.js";
import { extractSemanticObjects } from "../../core/semantic/index.js";
import { createSession } from "../../core/session.js";
import { cliState } from "../state.js";
import { formatNodeList } from "../output.js";

export function createAndroidCommand(): Command {
  const android = new Command("android").description(
    "Android application commands (adb + UiAutomator)",
  );

  android
    .command("boot")
    .description("Wait for an Android device to be ready")
    .option("--serial <s>", "Device serial")
    .option("--timeout <ms>", "Boot timeout in ms", "60000")
    .action(async (opts: AndroidBootOptions) => {
      const adb = new AdbClient({ deviceSerial: opts.serial });
      await adb.waitForDevice(parsePositiveInt(opts.timeout, "--timeout"));
      const devices = await adb.devices();
      process.stdout.write(`devices ready: ${String(devices.length)}\n`);
    });

  android
    .command("install")
    .description("Install an APK on the connected device")
    .argument("<apk>", "Path to APK file")
    .option("--serial <s>", "Device serial")
    .action(async (apk: string, opts: AndroidSerialOption) => {
      const adb = new AdbClient({ deviceSerial: opts.serial });
      await adb.install(apk);
      process.stdout.write(`installed: ${apk}\n`);
    });

  android
    .command("open")
    .description("Launch an app and establish a session")
    .argument("<target>", "Package name or component (pkg/.Activity)")
    .option("--serial <s>", "Device serial")
    .option("--replay", "Enable action replay recording")
    .option("--output <dir>", "Artifact output directory", "artifacts")
    .action(async (target: string, opts: AndroidOpenOptions) => {
      const session = createSession("android", target);
      cliState.setSessionId(session.id);

      if (opts.replay === true) {
        cliState.initReplay("android", target, opts.output);
      }

      const client = new AndroidClient({ deviceSerial: opts.serial });
      await client.connect(target);
      cliState.setAdapter(client);

      const nodes = await client.getNodes();
      cliState.setNodes(nodes);

      const screen = await client.getScreen();
      const patterns = detectPatterns(nodes);
      const semanticObjects = extractSemanticObjects(nodes);

      const snapshot = {
        session,
        screen,
        nodes,
        patterns,
        semanticObjects,
        artifacts: {
          screenshot: null,
          rawSource: null,
          normalizedSource: null,
        } as Artifacts,
      };
      cliState.setSnapshot(snapshot);

      process.stdout.write(
        `session: ${session.id}\ntarget: ${target}\nnodes: ${String(nodes.length)}\npatterns: ${String(patterns.length)}\n`,
      );
    });

  android
    .command("run")
    .description("Acquire, install, and launch an APK, then establish a session")
    .option("--apk <path>", "Local APK file path")
    .option("--app-id <id>", "Android application ID")
    .option("--play-url <url>", "Google Play URL (extracts app ID only)")
    .option("--provider <name>", "Enable an additional APK provider (e.g. fdroid)")
    .option("--serial <s>", "Device serial")
    .option("--output <dir>", "Artifact output directory", "artifacts")
    .action(async (opts: AndroidRunOptions) => {
      if (
        opts.apk === undefined &&
        opts.appId === undefined &&
        opts.playUrl === undefined
      ) {
        throw new Error("One of --apk, --app-id, or --play-url is required");
      }

      // Build provider chain based on flags
      const customProviders = [];
      const enabledProviders: string[] = ["local-file"];
      if (opts.provider === "fdroid") {
        customProviders.push(new FdroidProvider());
        enabledProviders.push("fdroid");
      }

      // Acquire APK through the provider chain
      const acquisition = await acquireApk(
        {
          apkPath: opts.apk,
          appId: opts.appId,
          playUrl: opts.playUrl,
        },
        {
          customProviders: customProviders.length > 0 ? customProviders : undefined,
          enabledProviders: customProviders.length > 0 ? enabledProviders : undefined,
        },
      );

      process.stderr.write(
        `acquired: ${acquisition.packageName} from ${acquisition.source}\n` +
          `sha256: ${acquisition.sha256}\n`,
      );

      const session = createSession("android", acquisition.packageName);
      cliState.setSessionId(session.id);

      const client = new AndroidClient({ deviceSerial: opts.serial });
      // Pass the package name so the app is launched after APK install
      await client.connect(acquisition.apkPath, {
        packageName: acquisition.packageName,
      });
      cliState.setAdapter(client);

      const [nodes, screen, screenshotBuf, rawSource] = await Promise.all([
        client.getNodes(),
        client.getScreen(),
        client.screenshot(),
        client.getRawSource(),
      ]);
      cliState.setNodes(nodes);

      const patterns = detectPatterns(nodes);
      const semanticObjects = extractSemanticObjects(nodes);
      const writer = new ArtifactWriter(opts.output);

      const snapshot = {
        session,
        screen,
        nodes,
        patterns,
        semanticObjects,
        artifacts: {
          screenshot: null,
          rawSource: null,
          normalizedSource: null,
        } as Artifacts,
      };

      const artifactPaths = await writer.writeAll(session.id, {
        screenshot: screenshotBuf,
        rawSource,
        snapshot,
      });
      snapshot.artifacts = artifactPaths;
      cliState.setSnapshot(snapshot);

      process.stdout.write(
        formatNodeList(nodes) + "\n",
      );
    });

  return android;
}

interface AndroidBootOptions {
  serial?: string;
  timeout: string;
}

interface AndroidSerialOption {
  serial?: string;
}

interface AndroidOpenOptions {
  serial?: string;
  replay?: boolean;
  output: string;
}

interface AndroidRunOptions {
  apk?: string;
  appId?: string;
  playUrl?: string;
  provider?: string;
  serial?: string;
  output: string;
}
