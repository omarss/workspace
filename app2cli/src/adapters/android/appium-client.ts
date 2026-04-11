import { withRetry } from "../../core/retry.js";
import type { Screen, UiNode } from "../../core/schema/index.js";
import { assignStableIds } from "../../core/stable-id.js";
import type { PlatformAdapter } from "../types.js";
import { AdbClient } from "./adb-client.js";
import { parseUiAutomatorXml } from "./uiautomator-parser.js";

/**
 * Options for the Android/Appium adapter.
 */
export interface AndroidClientOptions {
  /** ADB binary path (default: "adb") */
  adbPath?: string;
  /** Device serial (for multi-device setups) */
  deviceSerial?: string;
}

/**
 * Android adapter using adb + UiAutomator for extraction and actions.
 * Falls back to direct adb commands when Appium is not available.
 */
export class AndroidClient implements PlatformAdapter {
  readonly platform = "android" as const;

  private readonly adb: AdbClient;

  constructor(options: AndroidClientOptions = {}) {
    this.adb = new AdbClient({
      adbPath: options.adbPath,
      deviceSerial: options.deviceSerial,
    });
  }

  /**
   * Connect to a target and launch the app.
   *
   * Accepted target formats:
   * - APK file path: installs the APK, then launches using the provided packageName
   * - Component: "com.example.app/.MainActivity" — launches directly
   * - Package name: "com.example.app" — launches the default activity
   */
  async connect(
    target: string,
    options?: { packageName?: string },
  ): Promise<void> {
    await this.adb.waitForDevice();

    if (target.endsWith(".apk")) {
      await this.adb.install(target);

      // After installing an APK, we must explicitly launch the app.
      // Use the provided package name, or fall back to querying the device.
      const pkg = options?.packageName;
      if (typeof pkg === "string" && pkg.length > 0) {
        await this.adb.launch(pkg);
      }
      // If no package name is provided, the app was installed but not launched.
      // The caller (android run) is responsible for providing the package name.
    } else if (target.includes("/")) {
      // Component format: com.example.app/.MainActivity
      await this.adb.launch(target);
    } else {
      // Package format: launch default activity
      await this.adb.launch(target);
    }

    // Give the app time to render its first frame
    await new Promise((resolve) => {
      setTimeout(resolve, 2000);
    });
  }

  async getScreen(): Promise<Screen> {
    const activity = await this.adb.getCurrentActivity();
    const size = await this.adb.getScreenSize();

    return {
      title: activity.activityName,
      url: null,
      packageName: activity.packageName,
      activity: activity.activityName,
      width: size.width,
      height: size.height,
    };
  }

  async getNodes(): Promise<UiNode[]> {
    const xml = await this.adb.dumpUiHierarchy();
    const nodes = parseUiAutomatorXml(xml);
    return assignStableIds(nodes);
  }

  async screenshot(): Promise<Buffer> {
    return this.adb.screenshot();
  }

  async getRawSource(): Promise<string> {
    return this.adb.dumpUiHierarchy();
  }

  async click(nodeId: string, nodes: readonly UiNode[]): Promise<void> {
    const node = nodes.find((n) => n.id === nodeId);
    if (node === undefined) {
      throw new Error(`Node ${nodeId} not found`);
    }

    if (node.bounds === null) {
      throw new Error(`No bounds for node ${nodeId}`);
    }

    const centerX = node.bounds.x + node.bounds.width / 2;
    const centerY = node.bounds.y + node.bounds.height / 2;

    await withRetry(
      async () => {
        await this.adb.tap(centerX, centerY);
      },
      { maxAttempts: 2, initialDelayMs: 500 },
    );
  }

  async type(
    nodeId: string,
    text: string,
    nodes: readonly UiNode[],
  ): Promise<void> {
    // First tap to focus the field
    await this.click(nodeId, nodes);
    // Brief delay to let the keyboard appear
    await new Promise((resolve) => {
      setTimeout(resolve, 500);
    });

    await withRetry(
      async () => {
        await this.adb.inputText(text);
      },
      { maxAttempts: 2, initialDelayMs: 300 },
    );
  }

  disconnect(): Promise<void> {
    // No persistent connection to clean up with adb-based approach
    return Promise.resolve();
  }

  /**
   * Access the underlying ADB client for advanced operations.
   */
  getAdbClient(): AdbClient {
    return this.adb;
  }
}
