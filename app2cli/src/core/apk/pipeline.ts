import { assertValidProvenance } from "./provenance.js";
import { LocalFileProvider } from "./providers/local-file.js";
import { resolvePackageName } from "./resolve.js";
import type { ApkAcquisitionResult, ApkInput, ApkProvider } from "./types.js";

/**
 * Configuration for the APK acquisition pipeline.
 */
export interface AcquisitionConfig {
  /** Explicit list of enabled provider names. If empty, use defaults. */
  enabledProviders?: string[];
  /** Additional custom providers to register */
  customProviders?: ApkProvider[];
}

/**
 * APK acquisition pipeline.
 *
 * Resolves package name from input, walks the provider chain,
 * and returns the first successful acquisition with full provenance.
 *
 * Provider priority:
 * 1. Local file (if --apk was given)
 * 2. Internal trusted registry (custom providers)
 * 3. F-Droid (future)
 * 4. Explicit third-party plugin (off by default, must be enabled)
 */
export async function acquireApk(
  input: ApkInput,
  config: AcquisitionConfig = {},
): Promise<ApkAcquisitionResult> {
  const providers = buildProviderChain(input, config);

  if (providers.length === 0) {
    throw new Error(
      "No APK providers available. Provide --apk with a local file path, " +
        "or configure additional providers.",
    );
  }

  // Resolve package name (may be null for local APK)
  const packageName = resolvePackageName(input) ?? "unknown";

  // Walk providers in priority order
  for (const provider of providers) {
    const result = await provider.resolve(packageName);
    if (result !== null) {
      assertValidProvenance(result);
      return result;
    }
  }

  throw new Error(
    `No provider could supply APK for "${packageName}". ` +
      `Tried ${String(providers.length)} provider(s): ${providers.map((p) => p.name).join(", ")}`,
  );
}

/**
 * Build the ordered provider chain based on input and config.
 */
function buildProviderChain(
  input: ApkInput,
  config: AcquisitionConfig,
): ApkProvider[] {
  const providers: ApkProvider[] = [];
  const allowList = config.enabledProviders;

  // 1. Local file provider (always first if an APK path was given)
  if (input.apkPath !== undefined) {
    const local = new LocalFileProvider(input.apkPath);
    if (isEnabled(local, allowList)) {
      providers.push(local);
    }
  }

  // 2. Custom providers from config
  if (config.customProviders !== undefined) {
    for (const provider of config.customProviders) {
      if (isEnabled(provider, allowList)) {
        providers.push(provider);
      }
    }
  }

  return providers;
}

/**
 * Check if a provider is enabled, respecting the allowlist and default settings.
 */
function isEnabled(
  provider: ApkProvider,
  allowList: string[] | undefined,
): boolean {
  // If an explicit allowlist is provided, only those providers are active
  if (allowList !== undefined && allowList.length > 0) {
    return allowList.includes(provider.name);
  }

  // Otherwise, only providers enabled by default are active
  return provider.enabledByDefault;
}
