import { describe, expect, it } from "vitest";
import { isSensitiveField, redactObject, redactString } from "./redact.js";

describe("redactString", () => {
  it("redacts credit card numbers", () => {
    const input = "Card: 4111-1111-1111-1111 and 5500 0000 0000 0004";
    const result = redactString(input);
    expect(result).not.toContain("4111");
    expect(result).not.toContain("5500");
    expect(result).toContain("[REDACTED]");
  });

  it("redacts bearer tokens", () => {
    const input = "Authorization: Bearer abc123xyz";
    const result = redactString(input);
    expect(result).not.toContain("abc123xyz");
  });

  it("redacts JWT tokens", () => {
    const jwt =
      "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123";
    const result = redactString(`token: ${jwt}`);
    expect(result).not.toContain("eyJhbGci");
  });

  it("redacts emails in privacy mode", () => {
    const input = "user: test@example.com";
    const normal = redactString(input);
    expect(normal).toContain("test@example.com");

    const private_ = redactString(input, { privacyMode: true });
    expect(private_).not.toContain("test@example.com");
  });

  it("redacts phone numbers in privacy mode", () => {
    const input = "call +1-555-123-4567";
    const result = redactString(input, { privacyMode: true });
    expect(result).not.toContain("555-123-4567");
  });

  it("redacts SSN in privacy mode", () => {
    const input = "SSN: 123-45-6789";
    const result = redactString(input, { privacyMode: true });
    expect(result).not.toContain("123-45-6789");
  });

  it("applies custom patterns", () => {
    const result = redactString("internal-key-abc123", {
      customPatterns: [
        { name: "internal_key", pattern: /internal-key-\w+/g },
      ],
    });
    expect(result).not.toContain("abc123");
    expect(result).toContain("[REDACTED]");
  });

  it("uses custom replacement string", () => {
    const result = redactString("Card: 4111-1111-1111-1111", {
      replacement: "***",
    });
    expect(result).toContain("***");
    expect(result).not.toContain("[REDACTED]");
  });

  it("passes through clean strings unchanged", () => {
    const input = "Hello world, this is a normal message";
    expect(redactString(input)).toBe(input);
  });
});

describe("redactObject", () => {
  it("redacts sensitive field values", () => {
    const obj = {
      username: "alice",
      password: "s3cret",
      token: "abc123",
      data: "visible",
    };

    const result = redactObject(obj);
    expect(result.username).toBe("alice");
    expect(result.password).toBe("[REDACTED]");
    expect(result.token).toBe("[REDACTED]");
    expect(result.data).toBe("visible");
  });

  it("redacts nested objects", () => {
    const obj = {
      auth: {
        access_token: "mytoken",
        user: "bob",
      },
    };

    const result = redactObject(obj);
    expect(result.auth.access_token).toBe("[REDACTED]");
    expect(result.auth.user).toBe("bob");
  });

  it("redacts inline patterns in string values", () => {
    const obj = {
      log: "Bearer abc123xyz was used",
    };

    const result = redactObject(obj);
    expect(result.log).not.toContain("abc123xyz");
  });

  it("handles arrays", () => {
    const obj = {
      cookies: ["session_id=abc", "Bearer xyz"],
    };

    const result = redactObject(obj);
    expect(result.cookies[1]).not.toContain("xyz");
  });

  it("handles null and undefined", () => {
    const obj = { a: null, b: undefined, c: "ok" };
    const result = redactObject(obj);
    expect(result.a).toBeNull();
    expect(result.b).toBeUndefined();
    expect(result.c).toBe("ok");
  });

  it("preserves non-sensitive numeric fields", () => {
    const obj = { count: 42, password: "secret" };
    const result = redactObject(obj);
    expect(result.count).toBe(42);
    expect(result.password).toBe("[REDACTED]");
  });
});

describe("isSensitiveField", () => {
  it("identifies known sensitive field names", () => {
    expect(isSensitiveField("password")).toBe(true);
    expect(isSensitiveField("token")).toBe(true);
    expect(isSensitiveField("api_key")).toBe(true);
    expect(isSensitiveField("cookie")).toBe(true);
    expect(isSensitiveField("otp")).toBe(true);
  });

  it("is case-insensitive", () => {
    expect(isSensitiveField("PASSWORD")).toBe(true);
    expect(isSensitiveField("Token")).toBe(true);
  });

  it("rejects non-sensitive fields", () => {
    expect(isSensitiveField("username")).toBe(false);
    expect(isSensitiveField("email")).toBe(false);
    expect(isSensitiveField("name")).toBe(false);
  });
});
