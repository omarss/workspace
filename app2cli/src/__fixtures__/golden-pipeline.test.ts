import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { parseUiAutomatorXml } from "../adapters/android/uiautomator-parser.js";
import { rawNodesToUiNodes } from "../adapters/web/dom-extractor.js";
import type { RawWebNode } from "../adapters/web/dom-extractor.js";
import { detectPatterns } from "../core/patterns/index.js";
import { queryBestMatch, queryNodes } from "../core/query/index.js";
import { UiNodeSchema } from "../core/schema/index.js";

// ---- Android golden fixture ----

describe("golden: android login screen pipeline", () => {
  async function loadAndroidNodes(): Promise<ReturnType<typeof parseUiAutomatorXml>> {
    const xml = await readFile(
      join(import.meta.dirname, "android-login.xml"),
      "utf-8",
    );
    return parseUiAutomatorXml(xml);
  }

  it("all nodes validate against schema", async () => {
    const nodes = await loadAndroidNodes();
    for (const node of nodes) {
      expect(UiNodeSchema.safeParse(node).success).toBe(true);
    }
  });

  it("query finds email field by label", async () => {
    const nodes = await loadAndroidNodes();
    const match = queryBestMatch(nodes, "field labeled email");
    expect(match).not.toBeNull();
    expect(match?.node.name).toContain("Email");
    expect(match?.node.type).toBe("textbox");
  });

  it("query finds sign in button", async () => {
    const nodes = await loadAndroidNodes();
    const match = queryBestMatch(nodes, "button text sign in");
    expect(match).not.toBeNull();
    expect(match?.node.text).toBe("Sign in");
    expect(match?.node.clickable).toBe(true);
  });

  it("query finds password field", async () => {
    const nodes = await loadAndroidNodes();
    const match = queryBestMatch(nodes, "field labeled password");
    expect(match).not.toBeNull();
    expect(match?.node.name).toBe("Password");
  });

  it("detects login form pattern", async () => {
    const nodes = await loadAndroidNodes();
    const patterns = detectPatterns(nodes);
    const login = patterns.find((p) => p.kind === "login_form");
    expect(login).toBeDefined();
    expect(login?.confidence).toBeGreaterThanOrEqual(0.85);
  });

  it("query finds all buttons", async () => {
    const nodes = await loadAndroidNodes();
    const matches = queryNodes(nodes, "button");
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });
});

// ---- Web golden fixture ----

const webLoginFixture: RawWebNode = {
  tag: "html",
  text: "",
  role: "generic",
  ariaLabel: null,
  ariaDescribedby: null,
  placeholder: null,
  href: null,
  type: null,
  value: null,
  disabled: false,
  hidden: false,
  checked: null,
  ariaChecked: null,
  ariaSelected: null,
  bounds: { x: 0, y: 0, width: 1280, height: 720 },
  cssSelector: "html",
  children: [
    {
      tag: "nav",
      text: "",
      role: "navigation",
      ariaLabel: "Main navigation",
      ariaDescribedby: null,
      placeholder: null,
      href: null,
      type: null,
      value: null,
      disabled: false,
      hidden: false,
      checked: null,
      ariaChecked: null,
      ariaSelected: null,
      bounds: { x: 0, y: 0, width: 1280, height: 60 },
      cssSelector: "nav",
      children: [],
    },
    {
      tag: "form",
      text: "",
      role: "form",
      ariaLabel: "Sign in",
      ariaDescribedby: null,
      placeholder: null,
      href: null,
      type: null,
      value: null,
      disabled: false,
      hidden: false,
      checked: null,
      ariaChecked: null,
      ariaSelected: null,
      bounds: { x: 400, y: 200, width: 480, height: 300 },
      cssSelector: "form",
      children: [
        {
          tag: "input",
          text: "",
          role: "textbox",
          ariaLabel: "Email",
          ariaDescribedby: null,
          placeholder: "you@example.com",
          href: null,
          type: "email",
          value: "",
          disabled: false,
          hidden: false,
          checked: null,
          ariaChecked: null,
          ariaSelected: null,
          bounds: { x: 440, y: 260, width: 400, height: 40 },
          cssSelector: "input[type=\"email\"]",
          children: [],
        },
        {
          tag: "input",
          text: "",
          role: "textbox",
          ariaLabel: "Password",
          ariaDescribedby: null,
          placeholder: "password",
          href: null,
          type: "password",
          value: "",
          disabled: false,
          hidden: false,
          checked: null,
          ariaChecked: null,
          ariaSelected: null,
          bounds: { x: 440, y: 320, width: 400, height: 40 },
          cssSelector: "input[type=\"password\"]",
          children: [],
        },
        {
          tag: "button",
          text: "Sign in",
          role: "button",
          ariaLabel: null,
          ariaDescribedby: null,
          placeholder: null,
          href: null,
          type: "submit",
          value: null,
          disabled: false,
          hidden: false,
          checked: null,
          ariaChecked: null,
          ariaSelected: null,
          bounds: { x: 540, y: 400, width: 200, height: 48 },
          cssSelector: "button[type=\"submit\"]",
          children: [],
        },
        {
          tag: "a",
          text: "Forgot password?",
          role: "link",
          ariaLabel: null,
          ariaDescribedby: null,
          placeholder: null,
          href: "/reset",
          type: null,
          value: null,
          disabled: false,
          hidden: false,
          checked: null,
          ariaChecked: null,
          ariaSelected: null,
          bounds: { x: 540, y: 470, width: 200, height: 24 },
          cssSelector: "a",
          children: [],
        },
      ],
    },
  ],
};

describe("golden: web login page pipeline", () => {
  const nodes = rawNodesToUiNodes(webLoginFixture);

  it("all nodes validate against schema", () => {
    for (const node of nodes) {
      expect(UiNodeSchema.safeParse(node).success).toBe(true);
    }
  });

  it("query finds email field", () => {
    const match = queryBestMatch(nodes, "field labeled email");
    expect(match).not.toBeNull();
    expect(match?.node.name).toBe("Email");
    expect(match?.node.placeholder).toBe("you@example.com");
  });

  it("query finds sign in button", () => {
    const match = queryBestMatch(nodes, "button named sign in");
    expect(match).not.toBeNull();
    expect(match?.node.text).toBe("Sign in");
  });

  it("detects login form pattern", () => {
    const patterns = detectPatterns(nodes);
    const login = patterns.find((p) => p.kind === "login_form");
    expect(login).toBeDefined();
    expect(login?.confidence).toBeGreaterThanOrEqual(0.85);
  });

  it("detects top navigation pattern", () => {
    const patterns = detectPatterns(nodes);
    const nav = patterns.find((p) => p.kind === "top_navigation");
    expect(nav).toBeDefined();
  });

  it("query respects clickable filter", () => {
    const matches = queryNodes(nodes, "clickable button");
    expect(matches.length).toBeGreaterThanOrEqual(1);
    for (const m of matches) {
      expect(m.node.clickable).toBe(true);
    }
  });
});
