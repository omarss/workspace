import { createInterface } from "node:readline";
import type { Interface as ReadlineInterface } from "node:readline";
import type { PlatformAdapter } from "../adapters/types.js";
import { ReplayRecorder } from "../core/replay/index.js";
import type { Snapshot, UiNode } from "../core/schema/index.js";

/**
 * A prompt function that reads a line of input from the user.
 */
export type PromptFn = (message: string) => Promise<string>;

/**
 * Global CLI state — tracks the current session, adapter, nodes, and replay recorder.
 * This is a singleton used by all CLI commands to maintain context
 * between sequential operations like inspect -> query -> click.
 */
class CliState {
  private adapter: PlatformAdapter | null = null;
  private nodes: UiNode[] = [];
  private snapshot: Snapshot | null = null;
  private sessionId = "";
  private recorder: ReplayRecorder | null = null;
  private promptFn: PromptFn | null = null;

  setAdapter(adapter: PlatformAdapter): void {
    this.adapter = adapter;
  }

  getAdapter(): PlatformAdapter {
    if (this.adapter === null) {
      throw new Error(
        "No active session. Run 'app2cli web open <url>' or 'app2cli android open <target>' first.",
      );
    }
    return this.adapter;
  }

  hasAdapter(): boolean {
    return this.adapter !== null;
  }

  setNodes(nodes: UiNode[]): void {
    this.nodes = nodes;
  }

  getNodes(): UiNode[] {
    return this.nodes;
  }

  setSnapshot(snapshot: Snapshot): void {
    this.snapshot = snapshot;
  }

  getSnapshot(): Snapshot | null {
    return this.snapshot;
  }

  setSessionId(id: string): void {
    this.sessionId = id;
  }

  getSessionId(): string {
    return this.sessionId;
  }

  /**
   * Initialize replay recording for the current session.
   */
  initReplay(platform: string, target: string, outputDir: string): void {
    if (this.sessionId === "") {
      throw new Error("Session ID must be set before initializing replay");
    }
    this.recorder = new ReplayRecorder(
      this.sessionId,
      platform,
      target,
      outputDir,
    );
  }

  /**
   * Get the replay recorder (null if not recording).
   */
  getRecorder(): ReplayRecorder | null {
    return this.recorder;
  }

  /**
   * Set the shared readline and prompt function (called by the shell).
   * Commands like browse reuse this instead of creating their own readline.
   */
  setReadline(rl: ReadlineInterface): void {
    this.promptFn = (msg: string): Promise<string> =>
      new Promise((resolve) => {
        rl.question(msg, resolve);
      });
  }

  /**
   * Get a prompt function. Uses the shared readline if available,
   * otherwise creates a standalone one.
   */
  getPromptFn(): PromptFn {
    if (this.promptFn !== null) return this.promptFn;

    // Fallback: create standalone readline (for non-shell usage)
    const rl = createInterface({ input: process.stdin, output: process.stdout });
    return (msg: string): Promise<string> =>
      new Promise((resolve) => {
        rl.question(msg, (answer) => {
          rl.close();
          resolve(answer);
        });
      });
  }

  async cleanup(): Promise<void> {
    // Finalize replay if active
    if (this.recorder !== null) {
      const path = await this.recorder.finalize();
      process.stderr.write(`replay saved: ${path}\n`);
      this.recorder = null;
    }

    if (this.adapter !== null) {
      await this.adapter.disconnect();
      this.adapter = null;
    }
    this.nodes = [];
    this.snapshot = null;
    this.sessionId = "";
  }
}

/** Singleton CLI state instance. */
export const cliState = new CliState();
