import { describe, expect, it } from "vitest";
import { SessionSchema } from "./schema/index.js";
import { createSession, generateSessionId } from "./session.js";

describe("generateSessionId", () => {
  it("produces a string starting with sess_", () => {
    const id = generateSessionId();
    expect(id).toMatch(/^sess_[0-9a-f]{32}$/);
  });

  it("produces unique IDs", () => {
    const ids = new Set(Array.from({ length: 50 }, () => generateSessionId()));
    expect(ids.size).toBe(50);
  });
});

describe("createSession", () => {
  it("creates a valid web session", () => {
    const session = createSession("web", "https://example.com");
    expect(session.platform).toBe("web");
    expect(session.target).toBe("https://example.com");
    expect(session.id).toMatch(/^sess_/);
    expect(session.timestamp).toBeTruthy();

    const result = SessionSchema.safeParse(session);
    expect(result.success).toBe(true);
  });

  it("creates a valid android session", () => {
    const session = createSession("android", "com.example.app");
    expect(session.platform).toBe("android");
    expect(session.target).toBe("com.example.app");

    const result = SessionSchema.safeParse(session);
    expect(result.success).toBe(true);
  });

  it("produces ISO 8601 timestamp", () => {
    const session = createSession("web", "https://example.com");
    // ISO 8601 format check
    expect(() => new Date(session.timestamp)).not.toThrow();
    expect(new Date(session.timestamp).toISOString()).toBe(session.timestamp);
  });
});
