import type { Screen, UiNode } from "../core/schema/index.js";

/**
 * Shared interface for platform adapters.
 * Both web and android adapters implement this contract.
 */
export interface PlatformAdapter {
  /** Platform identifier */
  readonly platform: "web" | "android";

  /** Connect to the target (URL for web, device/APK for android) */
  connect(target: string, options?: { packageName?: string }): Promise<void>;

  /** Extract the current screen metadata */
  getScreen(): Promise<Screen>;

  /** Extract the full UI node tree */
  getNodes(): Promise<UiNode[]>;

  /** Take a screenshot, returns the image as a buffer */
  screenshot(): Promise<Buffer>;

  /** Get the raw page source (HTML for web, XML for android) */
  getRawSource(): Promise<string>;

  /** Perform a click/tap on a node */
  click(nodeId: string, nodes: readonly UiNode[]): Promise<void>;

  /** Type text into a node */
  type(
    nodeId: string,
    text: string,
    nodes: readonly UiNode[],
  ): Promise<void>;

  /** Navigate to a URL (web) or launch activity (android) mid-session */
  navigate?(target: string): Promise<void>;

  /** Disconnect and clean up */
  disconnect(): Promise<void>;
}
