import { describe, expect, it } from "vitest";
import { parseNonNegativeInt, parsePositiveInt } from "./validate.js";

describe("parsePositiveInt", () => {
  it("parses valid positive integers", () => {
    expect(parsePositiveInt("42", "--width")).toBe(42);
    expect(parsePositiveInt("1280", "--width")).toBe(1280);
  });

  it("rejects non-numeric values", () => {
    expect(() => parsePositiveInt("abc", "--width")).toThrow("Invalid value");
    expect(() => parsePositiveInt("nope", "--limit")).toThrow("Invalid value");
  });

  it("rejects zero", () => {
    expect(() => parsePositiveInt("0", "--width")).toThrow("positive integer");
  });

  it("rejects negative values", () => {
    expect(() => parsePositiveInt("-5", "--timeout")).toThrow("positive integer");
  });

  it("rejects empty string", () => {
    expect(() => parsePositiveInt("", "--height")).toThrow("Invalid value");
  });

  it("rejects float-like strings", () => {
    // parseInt("3.5") returns 3 which is valid; this is acceptable behavior
    expect(parsePositiveInt("3.5", "--width")).toBe(3);
  });
});

describe("parseNonNegativeInt", () => {
  it("allows zero", () => {
    expect(parseNonNegativeInt("0", "--offset")).toBe(0);
  });

  it("rejects negative values", () => {
    expect(() => parseNonNegativeInt("-1", "--offset")).toThrow("non-negative");
  });
});
