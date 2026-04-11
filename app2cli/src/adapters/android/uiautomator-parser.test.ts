import { describe, expect, it } from "vitest";
import { UiNodeSchema } from "../../core/schema/index.js";
import { parseUiAutomatorXml } from "./uiautomator-parser.js";

/** Minimal login screen UI hierarchy dump. */
const loginScreenXml = `<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.example.app" content-desc="" checkable="false" checked="false" clickable="false" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" visible-to-user="true" bounds="[0,0][1080,1920]">
    <node index="0" text="" resource-id="com.example.app:id/login_form" class="android.widget.LinearLayout" package="com.example.app" content-desc="Login Form" checkable="false" checked="false" clickable="false" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" visible-to-user="true" bounds="[100,400][980,1400]">
      <node index="0" text="" resource-id="com.example.app:id/email_input" class="android.widget.EditText" package="com.example.app" content-desc="Email" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" visible-to-user="true" bounds="[140,500][940,580]" />
      <node index="1" text="" resource-id="com.example.app:id/password_input" class="android.widget.EditText" package="com.example.app" content-desc="Password" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="false" password="true" selected="false" visible-to-user="true" bounds="[140,620][940,700]" />
      <node index="2" text="Sign in" resource-id="com.example.app:id/login_button" class="android.widget.Button" package="com.example.app" content-desc="" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" visible-to-user="true" bounds="[340,760][740,840]" />
      <node index="3" text="Forgot password?" resource-id="com.example.app:id/forgot_link" class="android.widget.TextView" package="com.example.app" content-desc="" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" visible-to-user="true" bounds="[380,880][700,920]" />
    </node>
  </node>
</hierarchy>`;

describe("parseUiAutomatorXml", () => {
  it("produces valid UiNode objects", () => {
    const nodes = parseUiAutomatorXml(loginScreenXml);
    for (const node of nodes) {
      const result = UiNodeSchema.safeParse(node);
      expect(result.success).toBe(true);
    }
  });

  it("assigns sequential IDs", () => {
    const nodes = parseUiAutomatorXml(loginScreenXml);
    const ids = nodes.map((n) => n.id);
    expect(ids).toContain("n_1");
    expect(ids).toContain("n_2");
  });

  it("extracts correct node count", () => {
    const nodes = parseUiAutomatorXml(loginScreenXml);
    // root FrameLayout + LinearLayout + 4 children = 6
    expect(nodes).toHaveLength(6);
  });

  it("maps EditText to textbox type and role", () => {
    const nodes = parseUiAutomatorXml(loginScreenXml);
    const emailNode = nodes.find((n) => n.name === "Email");
    expect(emailNode).toBeDefined();
    expect(emailNode?.type).toBe("textbox");
    expect(emailNode?.role).toBe("textbox");
  });

  it("maps Button to button type and role", () => {
    const nodes = parseUiAutomatorXml(loginScreenXml);
    const buttonNode = nodes.find((n) => n.text === "Sign in");
    expect(buttonNode).toBeDefined();
    expect(buttonNode?.type).toBe("button");
    expect(buttonNode?.role).toBe("button");
    expect(buttonNode?.clickable).toBe(true);
  });

  it("extracts content-desc as accessible name", () => {
    const nodes = parseUiAutomatorXml(loginScreenXml);
    const emailNode = nodes.find((n) => n.name === "Email");
    expect(emailNode?.name).toBe("Email");
  });

  it("extracts resource-id in android locator", () => {
    const nodes = parseUiAutomatorXml(loginScreenXml);
    const emailNode = nodes.find((n) => n.name === "Email");
    expect(emailNode?.locator.android?.resourceId).toBe(
      "com.example.app:id/email_input",
    );
  });

  it("parses bounds correctly", () => {
    const nodes = parseUiAutomatorXml(loginScreenXml);
    const button = nodes.find((n) => n.text === "Sign in");
    expect(button?.bounds).toEqual({
      x: 340,
      y: 760,
      width: 400,
      height: 80,
    });
  });

  it("tracks parent-child hierarchy", () => {
    const nodes = parseUiAutomatorXml(loginScreenXml);
    const formNode = nodes.find((n) => n.name === "Login Form");
    expect(formNode).toBeDefined();
    expect(formNode?.children).toHaveLength(4);
  });

  it("extracts clickable state", () => {
    const nodes = parseUiAutomatorXml(loginScreenXml);
    const emailNode = nodes.find((n) => n.name === "Email");
    expect(emailNode?.clickable).toBe(true);

    const rootNode = nodes.find(
      (n) => n.locator.android?.className === "android.widget.FrameLayout",
    );
    expect(rootNode?.clickable).toBe(false);
  });

  it("handles empty XML", () => {
    const nodes = parseUiAutomatorXml("");
    expect(nodes).toHaveLength(0);
  });

  it("handles XML with no nodes", () => {
    const nodes = parseUiAutomatorXml("<hierarchy></hierarchy>");
    expect(nodes).toHaveLength(0);
  });
});
