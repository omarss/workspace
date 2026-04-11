import type { ApkInput } from "./types.js";

/**
 * Resolve the Android package name from various input formats.
 *
 * Accepts:
 * - Direct app ID: "com.example.app"
 * - Play URL: "https://play.google.com/store/apps/details?id=com.example.app"
 * - Local APK path: not resolved here (returns null, caller handles separately)
 */
export function resolvePackageName(input: ApkInput): string | null {
  if (input.appId !== undefined) {
    return validatePackageName(input.appId.trim());
  }

  if (input.playUrl !== undefined) {
    return extractPackageFromPlayUrl(input.playUrl);
  }

  // Local APK path — package name extracted after install
  return null;
}

/**
 * Extract package name from a Google Play Store URL.
 * Only extracts the `id` parameter — does NOT attempt to download from Play.
 */
export function extractPackageFromPlayUrl(url: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error(`Invalid Google Play URL: ${url}`);
  }

  if (!parsed.hostname.endsWith("play.google.com")) {
    throw new Error(
      `Not a Google Play URL: ${url}. Expected hostname play.google.com`,
    );
  }

  const id = parsed.searchParams.get("id");
  if (id === null || id.trim().length === 0) {
    throw new Error(`Google Play URL does not contain an 'id' parameter: ${url}`);
  }

  return validatePackageName(id.trim());
}

/**
 * Validate that a string looks like a valid Android package name.
 * Format: reverse domain notation, e.g. "com.example.app"
 */
export function validatePackageName(name: string): string {
  // Android package names: letters, digits, dots, underscores
  // Must have at least two segments separated by dots
  const packageRegex = /^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$/;

  if (!packageRegex.test(name)) {
    throw new Error(
      `Invalid Android package name: "${name}". Expected format: com.example.app`,
    );
  }

  return name;
}
