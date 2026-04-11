import { describe, expect, it } from "vitest";
import {
  extractPackageFromPlayUrl,
  resolvePackageName,
  validatePackageName,
} from "./resolve.js";

describe("validatePackageName", () => {
  it("accepts valid package names", () => {
    expect(validatePackageName("com.example.app")).toBe("com.example.app");
    expect(validatePackageName("org.fdroid.fdroid")).toBe("org.fdroid.fdroid");
    expect(validatePackageName("com.android.chrome")).toBe("com.android.chrome");
    expect(validatePackageName("io.github.user.myapp")).toBe(
      "io.github.user.myapp",
    );
  });

  it("accepts names with underscores", () => {
    expect(validatePackageName("com.example.my_app")).toBe(
      "com.example.my_app",
    );
  });

  it("rejects single-segment names", () => {
    expect(() => validatePackageName("justoneword")).toThrow("Invalid");
  });

  it("rejects names starting with a digit", () => {
    expect(() => validatePackageName("1com.example.app")).toThrow("Invalid");
  });

  it("rejects names with spaces", () => {
    expect(() => validatePackageName("com.example. app")).toThrow("Invalid");
  });

  it("rejects empty string", () => {
    expect(() => validatePackageName("")).toThrow("Invalid");
  });
});

describe("extractPackageFromPlayUrl", () => {
  it("extracts package name from standard Play URL", () => {
    const url =
      "https://play.google.com/store/apps/details?id=com.example.app";
    expect(extractPackageFromPlayUrl(url)).toBe("com.example.app");
  });

  it("extracts from URL with extra query params", () => {
    const url =
      "https://play.google.com/store/apps/details?id=org.fdroid.fdroid&hl=en";
    expect(extractPackageFromPlayUrl(url)).toBe("org.fdroid.fdroid");
  });

  it("rejects non-Play URLs", () => {
    expect(() =>
      extractPackageFromPlayUrl("https://example.com/app?id=com.foo.bar"),
    ).toThrow("Not a Google Play URL");
  });

  it("rejects URLs without id param", () => {
    expect(() =>
      extractPackageFromPlayUrl("https://play.google.com/store/apps/details"),
    ).toThrow("does not contain an 'id' parameter");
  });

  it("rejects invalid URLs", () => {
    expect(() => extractPackageFromPlayUrl("not-a-url")).toThrow(
      "Invalid Google Play URL",
    );
  });
});

describe("resolvePackageName", () => {
  it("resolves from appId", () => {
    expect(resolvePackageName({ appId: "com.example.app" })).toBe(
      "com.example.app",
    );
  });

  it("resolves from playUrl", () => {
    expect(
      resolvePackageName({
        playUrl:
          "https://play.google.com/store/apps/details?id=com.example.app",
      }),
    ).toBe("com.example.app");
  });

  it("returns null for apkPath only", () => {
    expect(resolvePackageName({ apkPath: "./app.apk" })).toBeNull();
  });

  it("trims whitespace from appId", () => {
    expect(resolvePackageName({ appId: "  com.example.app  " })).toBe(
      "com.example.app",
    );
  });
});
