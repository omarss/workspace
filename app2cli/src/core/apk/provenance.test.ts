import { writeFile, rm, mkdir } from "node:fs/promises";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  assertValidProvenance,
  buildProvenance,
  computeFileSha256,
  getFileSize,
} from "./provenance.js";
import type { ApkAcquisitionResult } from "./types.js";

const TEST_DIR = join("artifacts", "_test_provenance");
const TEST_FILE = join(TEST_DIR, "test.apk");
const TEST_CONTENT = "fake-apk-content-for-hashing";

describe("provenance", () => {
  beforeEach(async () => {
    await mkdir(TEST_DIR, { recursive: true });
    await writeFile(TEST_FILE, TEST_CONTENT, "utf-8");
  });

  afterEach(async () => {
    await rm(TEST_DIR, { recursive: true, force: true });
  });

  describe("computeFileSha256", () => {
    it("computes a consistent hash", async () => {
      const hash1 = await computeFileSha256(TEST_FILE);
      const hash2 = await computeFileSha256(TEST_FILE);
      expect(hash1).toBe(hash2);
      expect(hash1).toMatch(/^[a-f0-9]{64}$/);
    });
  });

  describe("getFileSize", () => {
    it("returns correct file size", async () => {
      const size = await getFileSize(TEST_FILE);
      expect(size).toBe(Buffer.byteLength(TEST_CONTENT, "utf-8"));
    });
  });

  describe("buildProvenance", () => {
    it("produces complete provenance metadata", async () => {
      const result = await buildProvenance(
        TEST_FILE,
        "com.example.app",
        "local:./test.apk",
        "local",
      );

      expect(result.packageName).toBe("com.example.app");
      expect(result.apkPath).toBe(TEST_FILE);
      expect(result.sha256).toMatch(/^[a-f0-9]{64}$/);
      expect(result.fileSize).toBeGreaterThan(0);
      expect(result.source).toBe("local:./test.apk");
      expect(result.acquisitionMethod).toBe("local");
      expect(result.acquiredAt).toBeTruthy();
    });
  });

  describe("assertValidProvenance", () => {
    const validResult: ApkAcquisitionResult = {
      packageName: "com.example.app",
      apkPath: "/tmp/app.apk",
      sha256: "a".repeat(64),
      fileSize: 1024,
      source: "local",
      acquisitionMethod: "local",
      versionName: null,
      versionCode: null,
      signerInfo: null,
      acquiredAt: new Date().toISOString(),
    };

    it("passes for valid provenance", () => {
      expect(() => {
        assertValidProvenance(validResult);
      }).not.toThrow();
    });

    it("rejects empty packageName", () => {
      expect(() => {
        assertValidProvenance({ ...validResult, packageName: "" });
      }).toThrow("packageName");
    });

    it("rejects empty sha256", () => {
      expect(() => {
        assertValidProvenance({ ...validResult, sha256: "" });
      }).toThrow("sha256");
    });

    it("rejects zero fileSize", () => {
      expect(() => {
        assertValidProvenance({ ...validResult, fileSize: 0 });
      }).toThrow("fileSize");
    });

    it("rejects empty source", () => {
      expect(() => {
        assertValidProvenance({ ...validResult, source: "" });
      }).toThrow("source");
    });
  });
});
