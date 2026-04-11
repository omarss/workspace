import { mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { acquireApk } from "./pipeline.js";
import type { ApkAcquisitionResult, ApkProvider } from "./types.js";

const TEST_DIR = join("artifacts", "_test_pipeline");
const TEST_APK = join(TEST_DIR, "sample.apk");

describe("acquireApk", () => {
  beforeEach(async () => {
    await mkdir(TEST_DIR, { recursive: true });
    await writeFile(TEST_APK, "PK-fake-apk-data", "utf-8");
  });

  afterEach(async () => {
    await rm(TEST_DIR, { recursive: true, force: true });
  });

  it("acquires from local file path", async () => {
    const result = await acquireApk({ apkPath: TEST_APK });
    expect(result.acquisitionMethod).toBe("local");
    expect(result.sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(result.fileSize).toBeGreaterThan(0);
    expect(result.source).toContain("local:");
  });

  it("rejects when no providers can supply", async () => {
    await expect(
      acquireApk({ appId: "com.nonexistent.app" }),
    ).rejects.toThrow("No APK providers available");
  });

  it("walks provider chain and returns first success", async () => {
    const failProvider: ApkProvider = {
      name: "always-fail",
      requiresNetwork: false,
      enabledByDefault: true,
      resolve: () => Promise.resolve(null),
    };

    const successResult: ApkAcquisitionResult = {
      packageName: "com.test.app",
      apkPath: TEST_APK,
      sha256: "a".repeat(64),
      fileSize: 100,
      source: "test-registry",
      acquisitionMethod: "registry",
      versionName: "1.0.0",
      versionCode: "1",
      signerInfo: null,
      acquiredAt: new Date().toISOString(),
    };

    const successProvider: ApkProvider = {
      name: "test-success",
      requiresNetwork: false,
      enabledByDefault: true,
      resolve: () => Promise.resolve(successResult),
    };

    const result = await acquireApk(
      { appId: "com.test.app" },
      { customProviders: [failProvider, successProvider] },
    );

    expect(result.source).toBe("test-registry");
    expect(result.acquisitionMethod).toBe("registry");
  });

  it("respects enabledProviders allowlist", async () => {
    const disabledProvider: ApkProvider = {
      name: "disabled-one",
      requiresNetwork: true,
      enabledByDefault: false,
      resolve: () => {
        throw new Error("should not be called");
      },
    };

    await expect(
      acquireApk(
        { appId: "com.test.app" },
        {
          customProviders: [disabledProvider],
          enabledProviders: ["some-other-provider"],
        },
      ),
    ).rejects.toThrow("No APK providers available");
  });

  it("skips providers not in allowlist", async () => {
    const result: ApkAcquisitionResult = {
      packageName: "com.test.app",
      apkPath: TEST_APK,
      sha256: "b".repeat(64),
      fileSize: 200,
      source: "allowed-provider",
      acquisitionMethod: "registry",
      versionName: null,
      versionCode: null,
      signerInfo: null,
      acquiredAt: new Date().toISOString(),
    };

    const allowedProvider: ApkProvider = {
      name: "allowed",
      requiresNetwork: false,
      enabledByDefault: false,
      resolve: () => Promise.resolve(result),
    };

    const blockedProvider: ApkProvider = {
      name: "blocked",
      requiresNetwork: false,
      enabledByDefault: true,
      resolve: () => {
        throw new Error("should not be called");
      },
    };

    const acquired = await acquireApk(
      { appId: "com.test.app" },
      {
        customProviders: [blockedProvider, allowedProvider],
        enabledProviders: ["allowed"],
      },
    );

    expect(acquired.source).toBe("allowed-provider");
  });
});
