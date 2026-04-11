import { describe, expect, it } from "vitest";
import { assertActionSafe, classifyConfidence } from "./confidence.js";

describe("classifyConfidence", () => {
  it("classifies >= 0.95 as action_safe", () => {
    expect(classifyConfidence(0.95)).toBe("action_safe");
    expect(classifyConfidence(0.99)).toBe("action_safe");
    expect(classifyConfidence(1.0)).toBe("action_safe");
  });

  it("classifies 0.85-0.94 as query_safe", () => {
    expect(classifyConfidence(0.85)).toBe("query_safe");
    expect(classifyConfidence(0.90)).toBe("query_safe");
    expect(classifyConfidence(0.94)).toBe("query_safe");
  });

  it("classifies < 0.85 as ambiguous", () => {
    expect(classifyConfidence(0.84)).toBe("ambiguous");
    expect(classifyConfidence(0.5)).toBe("ambiguous");
    expect(classifyConfidence(0.0)).toBe("ambiguous");
  });
});

describe("assertActionSafe", () => {
  it("returns null for action-safe scores", () => {
    expect(assertActionSafe(0.98, false)).toBeNull();
    expect(assertActionSafe(1.0, false)).toBeNull();
  });

  it("returns error for query-safe scores without force", () => {
    const result = assertActionSafe(0.90, false);
    expect(result).not.toBeNull();
    expect(result).toContain("below the action threshold");
    expect(result).toContain("--force");
  });

  it("returns error for ambiguous scores without force", () => {
    const result = assertActionSafe(0.5, false);
    expect(result).not.toBeNull();
    expect(result).toContain("below the minimum threshold");
  });

  it("allows everything with --force", () => {
    expect(assertActionSafe(0.3, true)).toBeNull();
    expect(assertActionSafe(0.5, true)).toBeNull();
    expect(assertActionSafe(0.9, true)).toBeNull();
  });
});
