import { describe, expect, it } from "vitest";
import type { UiNode } from "../schema/index.js";
import { findByGeometry, findNearest, parseGeometryQuery } from "./geometry.js";

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

const spatialNodes: UiNode[] = [
  makeNode({
    id: "n_email",
    type: "textbox",
    role: "textbox",
    name: "Email",
    bounds: { x: 100, y: 100, width: 200, height: 40 },
  }),
  makeNode({
    id: "n_pass",
    type: "textbox",
    role: "textbox",
    name: "Password",
    bounds: { x: 100, y: 160, width: 200, height: 40 },
  }),
  makeNode({
    id: "n_submit",
    type: "button",
    role: "button",
    text: "Submit",
    clickable: true,
    bounds: { x: 150, y: 230, width: 100, height: 40 },
  }),
  makeNode({
    id: "n_cancel",
    type: "button",
    role: "button",
    text: "Cancel",
    clickable: true,
    bounds: { x: 350, y: 230, width: 100, height: 40 },
  }),
  makeNode({
    id: "n_logo",
    type: "image",
    role: "image",
    bounds: { x: 150, y: 20, width: 100, height: 50 },
  }),
];

describe("findByGeometry", () => {
  it("finds nearest nodes", () => {
    const matches = findByGeometry(spatialNodes, "n_email", "nearest");
    expect(matches.length).toBeGreaterThan(0);
    // Password field should be closest to email
    expect(matches[0]?.node.id).toBe("n_pass");
  });

  it("finds nodes below a reference", () => {
    const matches = findByGeometry(spatialNodes, "n_email", "below");
    const ids = matches.map((m) => m.node.id);
    expect(ids).toContain("n_pass");
    expect(ids).toContain("n_submit");
    expect(ids).not.toContain("n_logo");
  });

  it("finds nodes above a reference", () => {
    const matches = findByGeometry(spatialNodes, "n_pass", "above");
    const ids = matches.map((m) => m.node.id);
    expect(ids).toContain("n_email");
    expect(ids).toContain("n_logo");
  });

  it("finds nodes right of a reference", () => {
    const matches = findByGeometry(spatialNodes, "n_submit", "right");
    const ids = matches.map((m) => m.node.id);
    expect(ids).toContain("n_cancel");
  });

  it("applies filter function", () => {
    const matches = findByGeometry(
      spatialNodes,
      "n_email",
      "below",
      (n) => n.type === "button",
    );
    const ids = matches.map((m) => m.node.id);
    expect(ids).toContain("n_submit");
    expect(ids).not.toContain("n_pass");
  });

  it("returns empty for unknown reference", () => {
    const matches = findByGeometry(spatialNodes, "n_unknown", "nearest");
    expect(matches).toHaveLength(0);
  });

  it("results are sorted by distance", () => {
    const matches = findByGeometry(spatialNodes, "n_email", "nearest");
    for (let i = 1; i < matches.length; i++) {
      const prev = matches[i - 1];
      const curr = matches[i];
      if (prev !== undefined && curr !== undefined) {
        expect(prev.distance).toBeLessThanOrEqual(curr.distance);
      }
    }
  });
});

describe("findNearest", () => {
  it("finds the single nearest node", () => {
    const match = findNearest(spatialNodes, "n_email");
    expect(match).not.toBeNull();
    expect(match?.node.id).toBe("n_pass");
  });

  it("respects filter", () => {
    const match = findNearest(
      spatialNodes,
      "n_email",
      (n) => n.type === "button",
    );
    expect(match).not.toBeNull();
    expect(match?.node.id).toBe("n_submit");
  });

  it("returns null for unknown reference", () => {
    const match = findNearest(spatialNodes, "n_unknown");
    expect(match).toBeNull();
  });
});

describe("parseGeometryQuery", () => {
  it("parses 'nearest button to n_5'", () => {
    const result = parseGeometryQuery("nearest button to n_5");
    expect(result).toEqual({
      relation: "nearest",
      role: "button",
      referenceId: "n_5",
    });
  });

  it("parses 'button below n_3'", () => {
    const result = parseGeometryQuery("button below n_3");
    expect(result).toEqual({
      relation: "below",
      role: "button",
      referenceId: "n_3",
    });
  });

  it("parses 'input above n_7'", () => {
    const result = parseGeometryQuery("input above n_7");
    expect(result).toEqual({
      relation: "above",
      role: "input",
      referenceId: "n_7",
    });
  });

  it("parses 'link right of n_2'", () => {
    const result = parseGeometryQuery("link right of n_2");
    expect(result).toEqual({
      relation: "right",
      role: "link",
      referenceId: "n_2",
    });
  });

  it("returns null for non-geometry queries", () => {
    expect(parseGeometryQuery("button named sign in")).toBeNull();
    expect(parseGeometryQuery("n_14")).toBeNull();
    expect(parseGeometryQuery("field labeled email")).toBeNull();
  });
});
