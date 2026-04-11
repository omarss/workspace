import { execFile } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

/**
 * Thin wrapper around adb commands for device management,
 * APK installation, screenshots, and UI hierarchy dumping.
 */
export class AdbClient {
  private readonly adbPath: string;
  private readonly deviceSerial: string | undefined;

  constructor(options: AdbClientOptions = {}) {
    this.adbPath = options.adbPath ?? "adb";
    this.deviceSerial = options.deviceSerial;
  }

  /**
   * Run an adb command and return stdout.
   */
  private async exec(...args: string[]): Promise<string> {
    const fullArgs =
      this.deviceSerial !== undefined
        ? ["-s", this.deviceSerial, ...args]
        : args;

    const { stdout } = await execFileAsync(this.adbPath, fullArgs, {
      maxBuffer: 10 * 1024 * 1024,
    });
    return stdout;
  }

  /**
   * List connected devices.
   */
  async devices(): Promise<AdbDevice[]> {
    const output = await this.exec("devices", "-l");
    const lines = output.split("\n").slice(1);
    const devices: AdbDevice[] = [];

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed === "") continue;
      const parts = trimmed.split(/\s+/);
      const serial = parts[0];
      const state = parts[1];
      if (serial !== undefined && state !== undefined) {
        devices.push({ serial, state });
      }
    }

    return devices;
  }

  /**
   * Wait for device to be online (boot complete).
   */
  async waitForDevice(timeoutMs = 60000): Promise<void> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      try {
        const result = await this.exec(
          "shell",
          "getprop",
          "sys.boot_completed",
        );
        if (result.trim() === "1") return;
      } catch {
        // Device not ready yet
      }
      await new Promise((resolve) => {
        setTimeout(resolve, 1000);
      });
    }
    throw new Error(`Device not ready after ${String(timeoutMs)}ms`);
  }

  /**
   * Install an APK on the device.
   */
  async install(apkPath: string): Promise<void> {
    await this.exec("install", "-r", apkPath);
  }

  /**
   * Launch an app by package name or component (package/activity).
   */
  async launch(target: string): Promise<void> {
    if (target.includes("/")) {
      // Component format: com.example.app/.MainActivity
      await this.exec("shell", "am", "start", "-n", target);
    } else {
      // Package format: launch the default activity
      await this.exec(
        "shell",
        "monkey",
        "-p",
        target,
        "-c",
        "android.intent.category.LAUNCHER",
        "1",
      );
    }
  }

  /**
   * Take a screenshot and return it as a Buffer.
   */
  async screenshot(): Promise<Buffer> {
    const { stdout } = await execFileAsync(
      this.adbPath,
      [
        ...(this.deviceSerial !== undefined
          ? ["-s", this.deviceSerial]
          : []),
        "exec-out",
        "screencap",
        "-p",
      ],
      { maxBuffer: 10 * 1024 * 1024, encoding: "buffer" },
    );
    return Buffer.from(stdout);
  }

  /**
   * Dump the UI hierarchy XML using uiautomator.
   */
  async dumpUiHierarchy(): Promise<string> {
    await this.exec(
      "shell",
      "uiautomator",
      "dump",
      "/sdcard/window_dump.xml",
    );
    const xml = await this.exec("shell", "cat", "/sdcard/window_dump.xml");
    return xml;
  }

  /**
   * Get the current foreground activity.
   */
  async getCurrentActivity(): Promise<ActivityInfo> {
    const output = await this.exec(
      "shell",
      "dumpsys",
      "activity",
      "activities",
    );

    // Parse the mResumedActivity line
    const resumedMatch = /mResumedActivity.*?(\S+\/\S+)/.exec(output);
    const component = resumedMatch?.[1] ?? "";
    const parts = component.split("/");

    return {
      packageName: parts[0] ?? "",
      activityName: parts[1] ?? "",
    };
  }

  /**
   * Get screen dimensions.
   */
  async getScreenSize(): Promise<{ width: number; height: number }> {
    const output = await this.exec("shell", "wm", "size");
    const match = /(\d+)x(\d+)/.exec(output);
    return {
      width: parseInt(match?.[1] ?? "1080", 10),
      height: parseInt(match?.[2] ?? "1920", 10),
    };
  }

  /**
   * Tap at coordinates.
   */
  async tap(x: number, y: number): Promise<void> {
    await this.exec(
      "shell",
      "input",
      "tap",
      String(Math.round(x)),
      String(Math.round(y)),
    );
  }

  /**
   * Type text (requires focus on input field).
   */
  async inputText(text: string): Promise<void> {
    // Escape special characters for shell
    const escaped = text.replace(/ /g, "%s");
    await this.exec("shell", "input", "text", escaped);
  }

  /**
   * Press back button.
   */
  async back(): Promise<void> {
    await this.exec("shell", "input", "keyevent", "KEYCODE_BACK");
  }

  /**
   * Press home button.
   */
  async home(): Promise<void> {
    await this.exec("shell", "input", "keyevent", "KEYCODE_HOME");
  }

  /**
   * Save raw data to a file for artifact storage.
   */
  async saveScreenshot(data: Buffer, path: string): Promise<void> {
    await writeFile(path, data);
  }
}

export interface AdbClientOptions {
  adbPath?: string;
  deviceSerial?: string;
}

export interface AdbDevice {
  serial: string;
  state: string;
}

export interface ActivityInfo {
  packageName: string;
  activityName: string;
}
