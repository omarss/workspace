/**
 * Result of a successful APK acquisition.
 * Every field is mandatory provenance metadata.
 */
export interface ApkAcquisitionResult {
  /** Resolved Android package name */
  packageName: string;
  /** Path to the acquired APK file on local disk */
  apkPath: string;
  /** SHA-256 hash of the APK file */
  sha256: string;
  /** File size in bytes */
  fileSize: number;
  /** Name of the provider that supplied the APK */
  source: string;
  /** Method used: "local", "registry", "fdroid", "plugin" */
  acquisitionMethod: string;
  /** Version name if extractable (e.g. "1.2.3") */
  versionName: string | null;
  /** Version code if extractable (e.g. "42") */
  versionCode: string | null;
  /** Signer info if extractable */
  signerInfo: string | null;
  /** ISO 8601 timestamp of acquisition */
  acquiredAt: string;
}

/**
 * Pluggable APK provider interface.
 * Each provider attempts to resolve and fetch an APK for a given package name.
 */
export interface ApkProvider {
  /** Human-readable provider name */
  readonly name: string;
  /** Whether this provider requires network access */
  readonly requiresNetwork: boolean;
  /** Whether this provider is enabled by default */
  readonly enabledByDefault: boolean;

  /**
   * Attempt to resolve and fetch an APK for the given package name.
   * Returns null if this provider cannot supply the package.
   */
  resolve(packageName: string): Promise<ApkAcquisitionResult | null>;
}

/**
 * Input types for APK acquisition.
 */
export interface ApkInput {
  /** Direct path to a local APK file */
  apkPath?: string;
  /** Android application ID (e.g. "com.example.app") */
  appId?: string;
  /** Google Play URL */
  playUrl?: string;
}
