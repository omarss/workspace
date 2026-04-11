import { describe, expect, it } from "vitest";
import { UiNodeSchema } from "../schema/index.js";
import { normalizeWebNodes } from "./web-normalizer.js";
import type { RawWebNode } from "./web-normalizer.js";

/** Minimal login form fixture. */
const loginFormFixture: RawWebNode = {
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
      tag: "form",
      text: "",
      role: "form",
      ariaLabel: "Login",
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
          placeholder: "Enter your email",
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
          placeholder: "Enter password",
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
      ],
    },
  ],
};

describe("normalizeWebNodes", () => {
  it("produces valid UiNode objects", () => {
    const nodes = normalizeWebNodes(loginFormFixture);
    for (const node of nodes) {
      const result = UiNodeSchema.safeParse(node);
      expect(result.success).toBe(true);
    }
  });

  it("assigns sequential IDs", () => {
    const nodes = normalizeWebNodes(loginFormFixture);
    const ids = nodes.map((n) => n.id);
    expect(ids).toContain("n_1");
    expect(ids).toContain("n_2");
    expect(ids).toContain("n_3");
  });

  it("correctly normalizes a login form", () => {
    const nodes = normalizeWebNodes(loginFormFixture);

    // Find email input
    const emailNode = nodes.find((n) => n.name === "Email");
    expect(emailNode).toBeDefined();
    expect(emailNode?.type).toBe("textbox");
    expect(emailNode?.role).toBe("textbox");
    expect(emailNode?.placeholder).toBe("Enter your email");
    expect(emailNode?.clickable).toBe(true);
    expect(emailNode?.enabled).toBe(true);
    expect(emailNode?.visible).toBe(true);

    // Find submit button
    const submitNode = nodes.find((n) => n.text === "Sign in");
    expect(submitNode).toBeDefined();
    expect(submitNode?.type).toBe("button");
    expect(submitNode?.role).toBe("button");
    expect(submitNode?.clickable).toBe(true);
  });

  it("tracks parent-child hierarchy via children array", () => {
    const nodes = normalizeWebNodes(loginFormFixture);
    const formNode = nodes.find((n) => n.role === "form");
    expect(formNode).toBeDefined();
    expect(formNode?.children.length).toBe(3);
  });

  it("preserves bounds information", () => {
    const nodes = normalizeWebNodes(loginFormFixture);
    const button = nodes.find((n) => n.text === "Sign in");
    expect(button?.bounds).toEqual({
      x: 540,
      y: 400,
      width: 200,
      height: 48,
    });
  });

  it("sets web locator with CSS selector", () => {
    const nodes = normalizeWebNodes(loginFormFixture);
    const emailNode = nodes.find((n) => n.name === "Email");
    expect(emailNode?.locator.web?.css).toBe("input[type=\"email\"]");
  });

  it("handles disabled state", () => {
    const formNode = loginFormFixture.children[0];
    expect(formNode).toBeDefined();
    const emailInput = formNode?.children[0];
    expect(emailInput).toBeDefined();
    if (formNode === undefined || emailInput === undefined) return;

    const disabledInput: RawWebNode = { ...emailInput, disabled: true };
    const root: RawWebNode = {
      ...loginFormFixture,
      children: [{ ...formNode, children: [disabledInput] }],
    };
    const nodes = normalizeWebNodes(root);
    const emailNode = nodes.find((n) => n.name === "Email");
    expect(emailNode?.enabled).toBe(false);
  });

  it("handles hidden elements", () => {
    const formNode = loginFormFixture.children[0];
    expect(formNode).toBeDefined();
    const emailInput = formNode?.children[0];
    expect(emailInput).toBeDefined();
    if (formNode === undefined || emailInput === undefined) return;

    const hiddenInput: RawWebNode = { ...emailInput, hidden: true };
    const root: RawWebNode = {
      ...loginFormFixture,
      children: [{ ...formNode, children: [hiddenInput] }],
    };
    const nodes = normalizeWebNodes(root);
    const emailNode = nodes.find((n) => n.name === "Email");
    expect(emailNode?.visible).toBe(false);
  });

  it("resolves checked state from ariaChecked", () => {
    const checkbox: RawWebNode = {
      tag: "input",
      text: "",
      role: "checkbox",
      ariaLabel: "Remember me",
      ariaDescribedby: null,
      placeholder: null,
      href: null,
      type: "checkbox",
      value: null,
      disabled: false,
      hidden: false,
      checked: null,
      ariaChecked: "true",
      ariaSelected: null,
      bounds: null,
      cssSelector: "input[type=\"checkbox\"]",
      children: [],
    };
    const root: RawWebNode = { ...loginFormFixture, children: [checkbox] };
    const nodes = normalizeWebNodes(root);
    const cbNode = nodes.find((n) => n.name === "Remember me");
    expect(cbNode?.checked).toBe(true);
  });
});
