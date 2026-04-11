import { describe, expect, it } from "vitest";
import type { UiNode } from "./schema/index.js";
import { assignStableIds, generateStableId } from "./stable-id.js";

describe("generateStableId", () => {
  it("produces deterministic IDs for same input", () => {
    const attrs = {
      role: "button",
      type: "button",
      name: "Submit",
      text: "Submit",
      path: ["root", "form", "button[1]"],
      locatorKey: "button[type=\"submit\"]",
    };

    const id1 = generateStableId(attrs, 0);
    const id2 = generateStableId(attrs, 0);
    expect(id1).toBe(id2);
  });

  it("produces different IDs for different attributes", () => {
    const attrs1 = {
      role: "button",
      type: "button",
      name: "Submit",
      text: "Submit",
      path: ["root", "form", "button[1]"],
      locatorKey: null,
    };

    const attrs2 = {
      role: "button",
      type: "button",
      name: "Cancel",
      text: "Cancel",
      path: ["root", "form", "button[2]"],
      locatorKey: null,
    };

    const id1 = generateStableId(attrs1, 0);
    const id2 = generateStableId(attrs2, 0);
    expect(id1).not.toBe(id2);
  });

  it("has the expected format n_<hash>_<index>", () => {
    const id = generateStableId(
      {
        role: "textbox",
        type: "textbox",
        name: "Email",
        text: "",
        path: ["root", "form", "input[1]"],
        locatorKey: "input[type=\"email\"]",
      },
      5,
    );

    expect(id).toMatch(/^n_[a-f0-9]{8}_5$/);
  });
});

describe("assignStableIds", () => {
  function makeNode(overrides: Partial<UiNode> & { id: string }): UiNode {
    return {
      type: "container",
      role: "generic",
      text: "",
      name: null,
      description: null,
      value: null,
      placeholder: null,
      enabled: true,
      visible: true,
      clickable: false,
      focusable: false,
      checked: null,
      selected: false,
      bounds: null,
      locator: {},
      path: [],
      children: [],
      ...overrides,
    };
  }

  it("replaces sequential IDs with stable hashes", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_1",
        type: "button",
        role: "button",
        text: "Click me",
        path: ["root", "button[1]"],
        children: [],
      }),
    ];

    const result = assignStableIds(nodes);
    expect(result[0]?.id).not.toBe("n_1");
    expect(result[0]?.id).toMatch(/^n_[a-f0-9]{8}_0$/);
  });

  it("updates children references", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_1",
        type: "container",
        role: "form",
        path: ["root", "form[1]"],
        children: ["n_2"],
      }),
      makeNode({
        id: "n_2",
        type: "button",
        role: "button",
        text: "Submit",
        path: ["root", "form[1]", "button[1]"],
        children: [],
      }),
    ];

    const result = assignStableIds(nodes);
    const parent = result[0];
    const child = result[1];

    expect(parent).toBeDefined();
    expect(child).toBeDefined();
    if (parent !== undefined && child !== undefined) {
      expect(parent.children[0]).toBe(child.id);
    }
  });

  it("produces same IDs across multiple calls with same data", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_1",
        type: "button",
        role: "button",
        text: "Save",
        path: ["root", "button[1]"],
      }),
    ];

    const result1 = assignStableIds(nodes);
    const result2 = assignStableIds(nodes);
    expect(result1[0]?.id).toBe(result2[0]?.id);
  });
});
