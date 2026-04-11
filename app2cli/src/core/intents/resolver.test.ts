import { describe, expect, it } from "vitest";
import type { UiNode } from "../schema/index.js";
import { listIntentNames, resolveIntent, tryResolveAsIntent } from "./resolver.js";

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

const loginPage: UiNode[] = [
  makeNode({
    id: "n_1",
    type: "textbox",
    role: "textbox",
    name: "Email",
    placeholder: "Enter email",
  }),
  makeNode({
    id: "n_2",
    type: "textbox",
    role: "textbox",
    name: "Password",
  }),
  makeNode({
    id: "n_3",
    type: "button",
    role: "button",
    text: "Sign in",
    clickable: true,
  }),
  makeNode({
    id: "n_4",
    type: "link",
    role: "link",
    text: "Forgot password?",
    clickable: true,
  }),
  makeNode({
    id: "n_5",
    type: "button",
    role: "button",
    text: "Create account",
    clickable: true,
  }),
];

const dialogPage: UiNode[] = [
  makeNode({
    id: "n_d1",
    type: "dialog",
    role: "dialog",
    text: "Cookie consent",
  }),
  makeNode({
    id: "n_d2",
    type: "button",
    role: "button",
    text: "Got it",
    clickable: true,
  }),
  makeNode({
    id: "n_d3",
    type: "button",
    role: "button",
    text: "No thanks",
    clickable: true,
  }),
];

const searchPage: UiNode[] = [
  makeNode({
    id: "n_s1",
    type: "textbox",
    role: "searchbox",
    name: "Search",
    placeholder: "Search products...",
  }),
  makeNode({
    id: "n_s2",
    type: "button",
    role: "button",
    text: "Go",
    clickable: true,
  }),
];

describe("resolveIntent", () => {
  it("resolves 'login' to the sign-in button", () => {
    const match = resolveIntent("login", loginPage);
    expect(match).not.toBeNull();
    expect(match?.node.id).toBe("n_3");
    expect(match?.action).toBe("click");
    expect(match?.score).toBeGreaterThanOrEqual(0.9);
  });

  it("resolves 'signup' to the create account button", () => {
    const match = resolveIntent("signup", loginPage);
    expect(match).not.toBeNull();
    expect(match?.node.id).toBe("n_5");
  });

  it("resolves 'dismiss' to a dialog close button", () => {
    const match = resolveIntent("dismiss", dialogPage);
    expect(match).not.toBeNull();
    expect(match?.action).toBe("click");
    // Should pick "Got it" or "No thanks"
    expect(["n_d2", "n_d3"]).toContain(match?.node.id);
  });

  it("resolves 'search' to the search input", () => {
    const match = resolveIntent("search", searchPage);
    expect(match).not.toBeNull();
    expect(match?.node.id).toBe("n_s1");
  });

  it("returns null for unknown intents", () => {
    const match = resolveIntent("nonexistent", loginPage);
    expect(match).toBeNull();
  });

  it("returns null when intent doesn't apply to current screen", () => {
    const match = resolveIntent("login", searchPage);
    expect(match).toBeNull();
  });
});

describe("tryResolveAsIntent", () => {
  it("resolves known intent names", () => {
    const match = tryResolveAsIntent("login", loginPage);
    expect(match).not.toBeNull();
    expect(match?.intentName).toBe("login");
  });

  it("returns null for non-intent strings", () => {
    const match = tryResolveAsIntent("button named sign in", loginPage);
    expect(match).toBeNull();
  });

  it("is case-insensitive", () => {
    const match = tryResolveAsIntent("LOGIN", loginPage);
    expect(match).not.toBeNull();
  });

  it("trims whitespace", () => {
    const match = tryResolveAsIntent("  dismiss  ", dialogPage);
    expect(match).not.toBeNull();
  });
});

describe("listIntentNames", () => {
  it("lists all built-in intents", () => {
    const names = listIntentNames();
    expect(names).toContain("login");
    expect(names).toContain("signup");
    expect(names).toContain("continue");
    expect(names).toContain("submit");
    expect(names).toContain("dismiss");
    expect(names).toContain("back");
    expect(names).toContain("search");
    expect(names).toHaveLength(7);
  });
});
