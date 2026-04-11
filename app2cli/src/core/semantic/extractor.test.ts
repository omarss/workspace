import { describe, expect, it } from "vitest";
import type { UiNode } from "../schema/index.js";
import { extractForms, extractSemanticObjects } from "./extractor.js";

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

describe("extractSemanticObjects", () => {
  it("extracts forms from login page", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_form",
        type: "form",
        role: "form",
        name: "Login",
        children: ["n_email", "n_pass", "n_submit"],
      }),
      makeNode({
        id: "n_email",
        type: "textbox",
        role: "textbox",
        name: "Email",
        placeholder: "you@example.com",
      }),
      makeNode({
        id: "n_pass",
        type: "textbox",
        role: "textbox",
        name: "Password",
      }),
      makeNode({
        id: "n_submit",
        type: "button",
        role: "button",
        text: "Sign in",
        clickable: true,
      }),
    ];

    const objects = extractSemanticObjects(nodes);
    const formObj = objects.find((o) => o.kind === "form");
    expect(formObj).toBeDefined();
    expect(formObj?.label).toBe("Login");
    expect(formObj?.nodeIds).toContain("n_email");
    expect(formObj?.nodeIds).toContain("n_submit");
  });

  it("extracts primary actions", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_1",
        type: "button",
        role: "button",
        text: "Submit",
        clickable: true,
      }),
    ];

    const objects = extractSemanticObjects(nodes);
    const primary = objects.find((o) => o.kind === "action_primary");
    expect(primary).toBeDefined();
    expect(primary?.label).toBe("Submit");
  });

  it("extracts secondary actions", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_1",
        type: "button",
        role: "button",
        text: "Cancel",
        clickable: true,
      }),
    ];

    const objects = extractSemanticObjects(nodes);
    const secondary = objects.find((o) => o.kind === "action_secondary");
    expect(secondary).toBeDefined();
    expect(secondary?.label).toBe("Cancel");
  });

  it("extracts navigation regions", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_nav",
        type: "navigation",
        role: "navigation",
        name: "Main menu",
        children: ["n_link1", "n_link2"],
      }),
      makeNode({ id: "n_link1", type: "link", text: "Home", clickable: true }),
      makeNode({ id: "n_link2", type: "link", text: "About", clickable: true }),
    ];

    const objects = extractSemanticObjects(nodes);
    const nav = objects.find((o) => o.kind === "navigation_region");
    expect(nav).toBeDefined();
    expect(nav?.label).toBe("Main menu");
  });

  it("extracts dialogs", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_dialog",
        type: "dialog",
        role: "dialog",
        name: "Confirm action",
        children: ["n_ok"],
      }),
      makeNode({ id: "n_ok", type: "button", text: "OK", clickable: true }),
    ];

    const objects = extractSemanticObjects(nodes);
    const dialog = objects.find((o) => o.kind === "dialog");
    expect(dialog).toBeDefined();
    expect(dialog?.label).toBe("Confirm action");
  });

  it("extracts error messages", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_err",
        type: "text",
        role: "alert",
        text: "Something went wrong",
      }),
    ];

    const objects = extractSemanticObjects(nodes);
    const error = objects.find((o) => o.kind === "error_message");
    expect(error).toBeDefined();
    expect(error?.label).toBe("Something went wrong");
  });

  it("extracts success messages", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_ok",
        type: "text",
        text: "Order confirmed successfully",
      }),
    ];

    const objects = extractSemanticObjects(nodes);
    const success = objects.find((o) => o.kind === "success_message");
    expect(success).toBeDefined();
  });
});

describe("extractForms", () => {
  it("identifies form fields with correct types", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_form",
        type: "form",
        role: "form",
        name: "Signup",
        children: ["n_email", "n_pass", "n_agree", "n_submit"],
      }),
      makeNode({
        id: "n_email",
        type: "textbox",
        role: "textbox",
        name: "Email address",
        placeholder: "email",
      }),
      makeNode({
        id: "n_pass",
        type: "textbox",
        role: "textbox",
        name: "Password",
      }),
      makeNode({
        id: "n_agree",
        type: "checkbox",
        role: "checkbox",
        name: "I agree to terms",
      }),
      makeNode({
        id: "n_submit",
        type: "button",
        role: "button",
        text: "Sign in",
        clickable: true,
      }),
    ];

    const forms = extractForms(nodes);
    expect(forms).toHaveLength(1);

    const form = forms[0];
    expect(form?.label).toBe("Signup");
    expect(form?.fields).toHaveLength(3);

    const emailField = form?.fields.find((f) => f.inputNodeId === "n_email");
    expect(emailField?.fieldType).toBe("email");
    expect(emailField?.label).toBe("Email address");

    const passField = form?.fields.find((f) => f.inputNodeId === "n_pass");
    expect(passField?.fieldType).toBe("password");

    const checkField = form?.fields.find((f) => f.inputNodeId === "n_agree");
    expect(checkField?.fieldType).toBe("checkbox");

    expect(form?.primaryAction).toBe("n_submit");
  });

  it("creates implicit form when no explicit form container", () => {
    const nodes: UiNode[] = [
      makeNode({
        id: "n_1",
        type: "textbox",
        role: "textbox",
        name: "Username",
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
        text: "Log in",
        clickable: true,
      }),
    ];

    const forms = extractForms(nodes);
    expect(forms).toHaveLength(1);
    expect(forms[0]?.fields).toHaveLength(2);
    expect(forms[0]?.primaryAction).toBe("n_3");
  });

  it("returns empty when no form signals", () => {
    const nodes: UiNode[] = [
      makeNode({ id: "n_1", type: "text", text: "Hello world" }),
    ];

    const forms = extractForms(nodes);
    expect(forms).toHaveLength(0);
  });
});
