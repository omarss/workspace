import { describe, expect, it } from "vitest";
import { normalizeWebTarget } from "./playwright-client.js";

describe("normalizeWebTarget", () => {
  it("accepts https targets", () => {
    expect(normalizeWebTarget("https://example.com/login")).toBe(
      "https://example.com/login",
    );
  });

  it("accepts http targets", () => {
    expect(normalizeWebTarget("http://localhost:3000")).toBe(
      "http://localhost:3000/",
    );
  });

  it("rejects unsupported schemes", () => {
    expect(() => normalizeWebTarget("file:///etc/passwd")).toThrow(
      /Unsupported web target protocol/,
    );
  });

  it("rejects malformed targets", () => {
    expect(() => normalizeWebTarget("not a url")).toThrow(
      /Invalid web target URL/,
    );
  });
});
