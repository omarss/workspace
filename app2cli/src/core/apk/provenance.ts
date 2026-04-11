import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import type { ApkAcquisitionResult } from "./types.js";

/**
 * Compute the SHA-256 hash of a file.
 */
export async function computeFileSha256(filePath: string): Promise<string> {
  const data = await readFile(filePath);
  const hash = createHash("sha256");
  hash.update(data);
  return hash.digest("hex");
}

/**
 * Get the file size in bytes.
 */
export async function getFileSize(filePath: string): Promise<number> {
  const info = await stat(filePath);
  return info.size;
}

/**
 * Build provenance metadata for a locally-available APK file.
 */
export async function buildProvenance(
  apkPath: string,
  packageName: string,
  source: string,
  method: string,
): Promise<ApkAcquisitionResult> {
  const [sha256, fileSize] = await Promise.all([
    computeFileSha256(apkPath),
    getFileSize(apkPath),
  ]);

  return {
    packageName,
    apkPath,
    sha256,
    fileSize,
    source,
    acquisitionMethod: method,
    versionName: null,
    versionCode: null,
    signerInfo: null,
    acquiredAt: new Date().toISOString(),
  };
}

/**
 * Validate that an APK acquisition result has all mandatory provenance fields.
 * Throws if any required field is missing.
 */
export function assertValidProvenance(result: ApkAcquisitionResult): void {
  if (result.packageName.length === 0) {
    throw new Error("APK provenance: packageName is required");
  }
  if (result.apkPath.length === 0) {
    throw new Error("APK provenance: apkPath is required");
  }
  if (result.sha256.length === 0) {
    throw new Error("APK provenance: sha256 is required");
  }
  if (result.fileSize <= 0) {
    throw new Error("APK provenance: fileSize must be positive");
  }
  if (result.source.length === 0) {
    throw new Error("APK provenance: source is required");
  }
}
