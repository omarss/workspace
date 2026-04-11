import { describe, expect, it } from "vitest";
import type { UiNode } from "../schema/index.js";
import {
  findNodeById,
  parseQuery,
  queryBestMatch,
  queryNodes,
} from "./selector-engine.js";

/** Helper to create a minimal UiNode for testing. */
function makeNode(overrides: Partial<UiNode> & { id: string }): UiNode {
  return {
    type: "button",
    role: "button",
    text: "",
    name: null,
    description: null,
    value: null,
    placeholder: null,
    enabled: true,
    visible: true,
    clickable: true,
    focusable: true,
    checked: null,
    selected: false,
    bounds: null,
    locator: {},
    path: [],
    children: [],
    ...overrides,
  };
}

const testNodes: UiNode[] = [
  makeNode({
    id: "n_1",
    type: "textbox",
    role: "textbox",
    text: "",
    name: "Email",
    placeholder: "Enter your email",
    clickable: false,
  }),
  makeNode({
    id: "n_2",
    type: "textbox",
    role: "textbox",
    text: "",
    name: "Password",
    placeholder: "Enter password",
    clickable: false,
  }),
  makeNode({
    id: "n_3",
    type: "button",
    role: "button",
    text: "Sign in",
    name: "Sign in",
  }),
  makeNode({
    id: "n_4",
    type: "link",
    role: "link",
    text: "Forgot password?",
    name: "Forgot password?",
  }),
  makeNode({
    id: "n_5",
    type: "button",
    role: "button",
    text: "Continue with Google",
    name: "Continue with Google",
  }),
  makeNode({
    id: "n_6",
    type: "text",
    role: "text",
    text: "Welcome back",
    name: null,
    clickable: false,
    visible: true,
  }),
  makeNode({
    id: "n_7",
    type: "button",
    role: "button",
    text: "Hidden button",
    name: "Hidden button",
    visible: false,
  }),
];

describe("parseQuery", () => {
  it("parses sequential node id", () => {
    const parsed = parseQuery("n_14");
    expect(parsed.id).toBe("n_14");
  });

  it("parses stable hashed node id", () => {
    const parsed = parseQuery("n_deadbeef_0");
    expect(parsed.id).toBe("n_deadbeef_0");
  });

  it("parses stable hashed node id with longer hash", () => {
    const parsed = parseQuery("n_a1b2c3d4_12");
    expect(parsed.id).toBe("n_a1b2c3d4_12");
  });

  it("parses role + named", () => {
    const parsed = parseQuery("button named sign in");
    expect(parsed.role).toBe("button");
    expect(parsed.name).toBe("sign in");
  });

  it("parses field labeled", () => {
    const parsed = parseQuery("field labeled email");
    expect(parsed.role).toBe("field");
    expect(parsed.labeledAs).toBe("email");
  });

  it("parses clickable text contains", () => {
    const parsed = parseQuery("clickable text contains continue");
    expect(parsed.clickableOnly).toBe(true);
    expect(parsed.text).toBe("continue");
  });

  it("parses first visible button", () => {
    const parsed = parseQuery("first visible button");
    expect(parsed.visibleOnly).toBe(true);
    expect(parsed.role).toBe("button");
  });

  it("parses button text login", () => {
    const parsed = parseQuery("button text login");
    expect(parsed.role).toBe("button");
    expect(parsed.text).toBe("login");
  });
});

describe("queryNodes", () => {
  it("matches by exact id", () => {
    const matches = queryNodes(testNodes, "n_3");
    expect(matches).toHaveLength(1);
    expect(matches[0]?.node.id).toBe("n_3");
    expect(matches[0]?.score).toBe(1.0);
    expect(matches[0]?.matchedBy).toBe("exact_id");
  });

  it("matches button named sign in", () => {
    const matches = queryNodes(testNodes, "button named sign in");
    expect(matches.length).toBeGreaterThan(0);
    expect(matches[0]?.node.id).toBe("n_3");
    expect(matches[0]?.matchedBy).toBe("role_and_name");
  });

  it("matches field labeled email", () => {
    const matches = queryNodes(testNodes, "field labeled email");
    expect(matches.length).toBeGreaterThan(0);
    expect(matches[0]?.node.id).toBe("n_1");
  });

  it("matches clickable text contains continue", () => {
    const matches = queryNodes(
      testNodes,
      "clickable text contains continue",
    );
    expect(matches.length).toBeGreaterThan(0);
    expect(matches[0]?.node.id).toBe("n_5");
  });

  it("filters out hidden nodes with visible modifier", () => {
    const matches = queryNodes(testNodes, "first visible button");
    const ids = matches.map((m) => m.node.id);
    expect(ids).not.toContain("n_7");
  });

  it("returns empty array for no matches", () => {
    const matches = queryNodes(testNodes, "button named submit order");
    expect(matches).toHaveLength(0);
  });

  it("returns results sorted by score descending", () => {
    const matches = queryNodes(testNodes, "button");
    for (let i = 1; i < matches.length; i++) {
      const prev = matches[i - 1];
      const curr = matches[i];
      if (prev !== undefined && curr !== undefined) {
        expect(prev.score).toBeGreaterThanOrEqual(curr.score);
      }
    }
  });
});

describe("queryBestMatch", () => {
  it("returns the highest scored match", () => {
    const match = queryBestMatch(testNodes, "button named sign in");
    expect(match).not.toBeNull();
    expect(match?.node.id).toBe("n_3");
  });

  it("returns null when no match", () => {
    const match = queryBestMatch(testNodes, "n_999");
    expect(match).toBeNull();
  });
});

describe("findNodeById", () => {
  it("finds a node by id", () => {
    const node = findNodeById(testNodes, "n_1");
    expect(node).toBeDefined();
    expect(node?.name).toBe("Email");
  });

  it("returns undefined for unknown id", () => {
    const node = findNodeById(testNodes, "n_999");
    expect(node).toBeUndefined();
  });
});
