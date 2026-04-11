import { describe, expect, it } from "vitest";
import { FdroidProvider } from "./fdroid.js";

describe("FdroidProvider", () => {
  it("has correct metadata", () => {
    const provider = new FdroidProvider();
    expect(provider.name).toBe("fdroid");
    expect(provider.requiresNetwork).toBe(true);
    expect(provider.enabledByDefault).toBe(false);
  });

  it("returns null for non-existent packages", async () => {
    const provider = new FdroidProvider({
      // Use a non-existent repo URL to avoid actual network calls in tests
      repoUrl: "http://localhost:0/nonexistent",
    });

    const result = await provider.resolve("com.nonexistent.package.xyz");
    expect(result).toBeNull();
  });

  // Integration test — only runs when FDROID_INTEGRATION=1
  // eslint-disable-next-line @typescript-eslint/dot-notation -- env vars use bracket notation
  it.skipIf(process.env["FDROID_INTEGRATION"] !== "1")(
    "downloads F-Droid's own APK",
    async () => {
      const provider = new FdroidProvider({
        downloadDir: "artifacts/_test_fdroid",
      });

      const result = await provider.resolve("org.fdroid.fdroid");
      expect(result).not.toBeNull();
      expect(result?.packageName).toBe("org.fdroid.fdroid");
      expect(result?.acquisitionMethod).toBe("fdroid");
      expect(result?.sha256).toMatch(/^[a-f0-9]{64}$/);
    },
    60000,
  );
});
