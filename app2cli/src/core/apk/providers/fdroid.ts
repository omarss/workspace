import { createWriteStream } from "node:fs";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { pipeline } from "node:stream/promises";
import { buildProvenance } from "../provenance.js";
import type { ApkAcquisitionResult, ApkProvider } from "../types.js";

/**
 * Default F-Droid repository base URL.
 */
const DEFAULT_FDROID_REPO = "https://f-droid.org/repo";

/**
 * F-Droid APK provider.
 *
 * Fetches APKs from the F-Droid repository for packages that are
 * available there. Disabled by default — must be explicitly enabled.
 *
 * Limitations:
 * - Only works for apps actually published on F-Droid
 * - Does not parse the full F-Droid index (would require JAR parsing)
 * - Uses a simple URL convention to attempt download
 */
export class FdroidProvider implements ApkProvider {
  readonly name = "fdroid";
  readonly requiresNetwork = true;
  readonly enabledByDefault = false;

  private readonly repoUrl: string;
  private readonly downloadDir: string;

  constructor(options: FdroidProviderOptions = {}) {
    this.repoUrl = options.repoUrl ?? DEFAULT_FDROID_REPO;
    this.downloadDir = options.downloadDir ?? join("artifacts", "_apk_cache");
  }

  async resolve(packageName: string): Promise<ApkAcquisitionResult | null> {
    // F-Droid uses the convention: {repo}/{packageName}_{versionCode}.apk
    // Without the index, we try the package listing page to get the latest version.
    // For now, we attempt a direct download using the package name.

    const apkListUrl = `https://f-droid.org/api/v1/packages/${packageName}`;

    let latestVersionCode: string;

    try {
      const response = await fetch(apkListUrl);
      if (!response.ok) return null;

      const data = await response.json() as FdroidPackageInfo;
      if (data.suggestedVersionCode === undefined) return null;
      latestVersionCode = String(data.suggestedVersionCode);
    } catch {
      // Package not found on F-Droid
      return null;
    }

    // Download the APK
    const apkUrl = `${this.repoUrl}/${packageName}_${latestVersionCode}.apk`;
    const localPath = await this.downloadApk(apkUrl, packageName, latestVersionCode);
    if (localPath === null) return null;

    const provenance = await buildProvenance(
      localPath,
      packageName,
      `fdroid:${apkUrl}`,
      "fdroid",
    );

    provenance.versionCode = latestVersionCode;
    return provenance;
  }

  private async downloadApk(
    url: string,
    packageName: string,
    versionCode: string,
  ): Promise<string | null> {
    try {
      await mkdir(this.downloadDir, { recursive: true });
      const filename = `${packageName}_${versionCode}.apk`;
      const localPath = join(this.downloadDir, filename);

      const response = await fetch(url);
      if (!response.ok || response.body === null) return null;

      const writer = createWriteStream(localPath);
      // Use pipeline to stream the response body to disk
      await pipeline(response.body, writer);

      return localPath;
    } catch {
      return null;
    }
  }
}

export interface FdroidProviderOptions {
  /** F-Droid repo base URL */
  repoUrl?: string;
  /** Local directory to cache downloaded APKs */
  downloadDir?: string;
}

interface FdroidPackageInfo {
  packageName?: string;
  suggestedVersionCode?: number;
  suggestedVersionName?: string;
}
