import { access, constants } from "node:fs/promises";
import { buildProvenance } from "../provenance.js";
import type { ApkAcquisitionResult, ApkProvider } from "../types.js";

/**
 * Local file APK provider.
 * Resolves when the package name matches a local file path that exists.
 * This is the highest-priority provider — no network needed.
 */
export class LocalFileProvider implements ApkProvider {
  readonly name = "local-file";
  readonly requiresNetwork = false;
  readonly enabledByDefault = true;

  private readonly filePath: string;

  constructor(filePath: string) {
    this.filePath = filePath;
  }

  async resolve(packageName: string): Promise<ApkAcquisitionResult | null> {
    // Check if the file exists and is readable
    try {
      await access(this.filePath, constants.R_OK);
    } catch {
      return null;
    }

    return buildProvenance(
      this.filePath,
      packageName,
      `local:${this.filePath}`,
      "local",
    );
  }
}
