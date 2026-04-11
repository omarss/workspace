import { Command } from "commander";
import { PlaywrightClient } from "../../adapters/web/index.js";
import { parsePositiveInt } from "../validate.js";
import { ArtifactWriter } from "../../core/artifacts/index.js";
import { detectPatterns } from "../../core/patterns/index.js";
import type { Artifacts } from "../../core/schema/index.js";
import { extractSemanticObjects } from "../../core/semantic/index.js";
import { createSession } from "../../core/session.js";
import { cliState } from "../state.js";
import { formatNodeList, formatSnapshotJson } from "../output.js";

export function createWebCommand(): Command {
  const web = new Command("web").description(
    "Web application commands (Playwright + Chromium)",
  );

  web
    .command("open")
    .description("Open a web page and establish a session")
    .argument("<url>", "URL to open")
    .option("--cdp <url>", "Connect via CDP endpoint")
    .option("--headless", "Run headless (default: true)", true)
    .option("--no-headless", "Run with visible browser")
    .option("--width <n>", "Viewport width", "1280")
    .option("--height <n>", "Viewport height", "720")
    .option("--replay", "Enable action replay recording")
    .option("--output <dir>", "Artifact output directory", "artifacts")
    .action(async (url: string, opts: WebOpenOptions) => {
      const session = createSession("web", url);
      cliState.setSessionId(session.id);

      if (opts.replay === true) {
        cliState.initReplay("web", url, opts.output);
      }

      const client = new PlaywrightClient({
        cdpUrl: opts.cdp,
        headless: opts.headless,
        viewportWidth: parsePositiveInt(opts.width, "--width"),
        viewportHeight: parsePositiveInt(opts.height, "--height"),
      });

      await client.connect(url);
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
        artifacts: { screenshot: null, rawSource: null, normalizedSource: null } as Artifacts,
      };
      cliState.setSnapshot(snapshot);

      process.stdout.write(
        `session: ${session.id}\ntarget: ${url}\nnodes: ${String(nodes.length)}\npatterns: ${String(patterns.length)}\n`,
      );
    });

  web
    .command("snapshot")
    .description("Take a full snapshot of a web page (non-interactive)")
    .argument("<url>", "URL to snapshot")
    .option("--cdp <url>", "Connect via CDP endpoint")
    .option("--output <dir>", "Artifact output directory", "artifacts")
    .option("--format <fmt>", "Output format: json or text", "json")
    .action(async (url: string, opts: WebSnapshotOptions) => {
      const session = createSession("web", url);
      const client = new PlaywrightClient({ cdpUrl: opts.cdp });

      try {
        await client.connect(url);
        const [nodes, screen, screenshotBuf, rawSource] = await Promise.all([
          client.getNodes(),
          client.getScreen(),
          client.screenshot(),
          client.getRawSource(),
        ]);

        const patterns = detectPatterns(nodes);
        const semanticObjects = extractSemanticObjects(nodes);
        const writer = new ArtifactWriter(opts.output);

        const snapshot = {
          session,
          screen,
          nodes,
          patterns,
          semanticObjects,
          artifacts: { screenshot: null, rawSource: null, normalizedSource: null } as Artifacts,
        };

        const artifactPaths = await writer.writeAll(session.id, {
          screenshot: screenshotBuf,
          rawSource,
          snapshot,
        });

        snapshot.artifacts = artifactPaths;

        if (opts.format === "json") {
          process.stdout.write(formatSnapshotJson(snapshot) + "\n");
        } else {
          process.stdout.write(formatNodeList(nodes) + "\n");
        }
      } finally {
        await client.disconnect();
      }
    });

  return web;
}

interface WebOpenOptions {
  cdp?: string;
  headless: boolean;
  width: string;
  height: string;
  replay?: boolean;
  output: string;
}

interface WebSnapshotOptions {
  cdp?: string;
  output: string;
  format: string;
}
