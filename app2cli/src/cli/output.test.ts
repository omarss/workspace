import { describe, expect, it } from "vitest";
import type { PatternMatch, UiNode } from "../core/schema/index.js";
import type { QueryMatch } from "../core/query/index.js";
import { formatNodeList, formatPatterns, formatQueryResults } from "./output.js";

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

describe("formatNodeList", () => {
  it("formats visible nodes as table rows", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_1",
        type: "button",
        text: "Sign in",
        clickable: true,
        enabled: true,
      }),
      makeNode({
        id: "n_2",
        type: "textbox",
        text: "",
        name: "Email",
        focusable: true,
        enabled: true,
      }),
    ];

    const output = formatNodeList(nodes);
    expect(output).toContain("[n_1]");
    expect(output).toContain("button");
    expect(output).toContain("Sign in");
    expect(output).toContain("clickable");
    expect(output).toContain("[n_2]");
    expect(output).toContain("Email");
  });

  it("skips invisible nodes", () => {
    const nodes: UiNode[] = [
      makeNode({ id: "n_1", type: "button", text: "Visible", visible: true }),
      makeNode({ id: "n_2", type: "button", text: "Hidden", visible: false }),
    ];

    const output = formatNodeList(nodes);
    expect(output).toContain("Visible");
    expect(output).not.toContain("Hidden");
  });

  it("truncates long text", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_1",
        type: "text",
        text: "This is a very long text that should be truncated at some point",
      }),
    ];

    const output = formatNodeList(nodes);
    expect(output).toContain("...");
    expect(output.length).toBeLessThan(200);
  });
});

describe("formatQueryResults", () => {
  it("formats matches with score and details", () => {
    const matches: QueryMatch[] = [
      {
        node: makeNode({
          id: "n_1",
          type: "button",
          text: "Sign in",
          bounds: { x: 100, y: 200, width: 180, height: 48 },
        }),
        score: 0.98,
        matchedBy: "role_and_name",
      },
    ];

    const output = formatQueryResults(matches);
    expect(output).toContain("match: n_1");
    expect(output).toContain("score: 0.98");
    expect(output).toContain("matched_by: role_and_name");
    expect(output).toContain("bounds: 100,200 180x48");
  });

  it("returns message for no matches", () => {
    const output = formatQueryResults([]);
    expect(output).toBe("no matches found");
  });
});

describe("formatPatterns", () => {
  it("formats pattern matches with evidence", () => {
    const patterns: PatternMatch[] = [
      {
        id: "pat_login_form_1",
        kind: "login_form",
        confidence: 0.97,
        evidence: {
          fields: ["n_1", "n_2"],
          actions: ["n_3"],
          texts: ["Sign in"],
        },
      },
    ];

    const output = formatPatterns(patterns);
    expect(output).toContain("login_form");
    expect(output).toContain("0.97");
    expect(output).toContain("n_1, n_2");
    expect(output).toContain("n_3");
  });

  it("returns message for no patterns", () => {
    const output = formatPatterns([]);
    expect(output).toBe("no patterns detected");
  });
});
