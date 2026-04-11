import { describe, expect, it } from "vitest";
import { BoundsSchema, LocatorSchema, UiNodeSchema } from "./ui-node.js";

describe("BoundsSchema", () => {
  it("validates a correct bounds object", () => {
    const result = BoundsSchema.safeParse({
      x: 100,
      y: 200,
      width: 180,
      height: 48,
    });
    expect(result.success).toBe(true);
  });

  it("rejects missing fields", () => {
    const result = BoundsSchema.safeParse({ x: 100, y: 200 });
    expect(result.success).toBe(false);
  });

  it("rejects non-numeric values", () => {
    const result = BoundsSchema.safeParse({
      x: "100",
      y: 200,
      width: 180,
      height: 48,
    });
    expect(result.success).toBe(false);
  });
});

describe("LocatorSchema", () => {
  it("validates a web-only locator", () => {
    const result = LocatorSchema.safeParse({
      web: { css: "button[type='submit']" },
    });
    expect(result.success).toBe(true);
  });

  it("validates an android-only locator", () => {
    const result = LocatorSchema.safeParse({
      android: { resourceId: "com.example:id/login_btn" },
    });
    expect(result.success).toBe(true);
  });

  it("validates an empty locator", () => {
    const result = LocatorSchema.safeParse({});
    expect(result.success).toBe(true);
  });
});

describe("UiNodeSchema", () => {
  const validNode = {
    id: "n_1",
    type: "button",
    role: "button",
    text: "Sign in",
    name: "Sign in",
    description: null,
    value: null,
    placeholder: null,
    enabled: true,
    visible: true,
    clickable: true,
    focusable: true,
    checked: null,
    selected: false,
    bounds: { x: 640, y: 410, width: 180, height: 48 },
    locator: { web: { css: "button[type='submit']" } },
    path: ["root", "main", "form", "button[1]"],
    children: [],
  };

  it("validates a complete node", () => {
    const result = UiNodeSchema.safeParse(validNode);
    expect(result.success).toBe(true);
  });

  it("validates a node with null bounds", () => {
    const result = UiNodeSchema.safeParse({ ...validNode, bounds: null });
    expect(result.success).toBe(true);
  });

  it("rejects a node missing required fields", () => {
    const { id: _, ...incomplete } = validNode;
    const result = UiNodeSchema.safeParse(incomplete);
    expect(result.success).toBe(false);
  });

  it("rejects non-boolean enabled field", () => {
    const result = UiNodeSchema.safeParse({
      ...validNode,
      enabled: "true",
    });
    expect(result.success).toBe(false);
  });
});
