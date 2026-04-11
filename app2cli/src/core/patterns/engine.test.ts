import { describe, expect, it } from "vitest";
import type { UiNode } from "../schema/index.js";
import { detectPatterns } from "./engine.js";

/** Helper to create a minimal UiNode. */
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

describe("detectPatterns", () => {
  describe("login form detection", () => {
    const loginNodes: UiNode[] = [
      makeNode({
        id: "n_1",
        type: "textbox",
        role: "textbox",
        name: "Email",
        placeholder: "Enter your email",
      }),
      makeNode({
        id: "n_2",
        type: "textbox",
        role: "textbox",
        name: "Password",
        placeholder: "Enter password",
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
    ];

    it("detects a login form", () => {
      const patterns = detectPatterns(loginNodes);
      const login = patterns.find((p) => p.kind === "login_form");
      expect(login).toBeDefined();
      expect(login?.confidence).toBeGreaterThanOrEqual(0.85);
    });

    it("includes field and action evidence", () => {
      const patterns = detectPatterns(loginNodes);
      const login = patterns.find((p) => p.kind === "login_form");
      expect(login?.evidence.fields?.length).toBeGreaterThan(0);
      expect(login?.evidence.actions?.length).toBeGreaterThan(0);
    });
  });

  describe("modal dialog detection", () => {
    const dialogNodes: UiNode[] = [
      makeNode({
        id: "n_1",
        type: "dialog",
        role: "dialog",
        text: "Are you sure?",
      }),
      makeNode({
        id: "n_2",
        type: "button",
        role: "button",
        text: "Cancel",
        clickable: true,
      }),
      makeNode({
        id: "n_3",
        type: "button",
        role: "button",
        text: "OK",
        clickable: true,
      }),
    ];

    it("detects a modal dialog", () => {
      const patterns = detectPatterns(dialogNodes);
      const dialog = patterns.find((p) => p.kind === "modal_dialog");
      expect(dialog).toBeDefined();
      expect(dialog?.confidence).toBeGreaterThanOrEqual(0.8);
    });
  });

  describe("error state detection", () => {
    const errorNodes: UiNode[] = [
      makeNode({
        id: "n_1",
        type: "text",
        role: "text",
        text: "Something went wrong",
      }),
      makeNode({
        id: "n_2",
        type: "button",
        role: "button",
        text: "Try again",
        clickable: true,
      }),
    ];

    it("detects an error state", () => {
      const patterns = detectPatterns(errorNodes);
      const error = patterns.find((p) => p.kind === "error_state");
      expect(error).toBeDefined();
      expect(error?.confidence).toBeGreaterThanOrEqual(0.7);
    });

    it("includes retry action in evidence", () => {
      const patterns = detectPatterns(errorNodes);
      const error = patterns.find((p) => p.kind === "error_state");
      expect(error?.evidence.actions?.length).toBeGreaterThan(0);
    });
  });

  describe("bottom navigation detection", () => {
    const navNodes: UiNode[] = [
      makeNode({
        id: "n_nav",
        type: "navigation",
        role: "navigation",
        bounds: { x: 0, y: 1800, width: 1080, height: 120 },
        children: ["n_t1", "n_t2", "n_t3", "n_t4"],
      }),
      makeNode({
        id: "n_t1",
        type: "button",
        role: "tab",
        text: "Home",
        clickable: true,
        selected: true,
        bounds: { x: 0, y: 1800, width: 270, height: 120 },
      }),
      makeNode({
        id: "n_t2",
        type: "button",
        role: "tab",
        text: "Search",
        clickable: true,
        bounds: { x: 270, y: 1800, width: 270, height: 120 },
      }),
      makeNode({
        id: "n_t3",
        type: "button",
        role: "tab",
        text: "Cart",
        clickable: true,
        bounds: { x: 540, y: 1800, width: 270, height: 120 },
      }),
      makeNode({
        id: "n_t4",
        type: "button",
        role: "tab",
        text: "Profile",
        clickable: true,
        bounds: { x: 810, y: 1800, width: 270, height: 120 },
      }),
    ];

    it("detects bottom navigation", () => {
      const patterns = detectPatterns(navNodes);
      const nav = patterns.find((p) => p.kind === "bottom_navigation");
      expect(nav).toBeDefined();
      expect(nav?.confidence).toBeGreaterThanOrEqual(0.8);
    });

    it("includes all nav items in evidence", () => {
      const patterns = detectPatterns(navNodes);
      const nav = patterns.find((p) => p.kind === "bottom_navigation");
      expect(nav?.evidence.items?.length).toBe(4);
    });
  });

  describe("OTP screen detection", () => {
    const otpNodes: UiNode[] = [
      makeNode({
        id: "n_1",
        type: "text",
        role: "text",
        text: "Enter verification code",
      }),
      makeNode({
        id: "n_2",
        type: "textbox",
        role: "textbox",
        name: "Digit 1",
      }),
      makeNode({
        id: "n_3",
        type: "textbox",
        role: "textbox",
        name: "Digit 2",
      }),
      makeNode({
        id: "n_4",
        type: "textbox",
        role: "textbox",
        name: "Digit 3",
      }),
      makeNode({
        id: "n_5",
        type: "textbox",
        role: "textbox",
        name: "Digit 4",
      }),
      makeNode({
        id: "n_6",
        type: "textbox",
        role: "textbox",
        name: "Digit 5",
      }),
      makeNode({
        id: "n_7",
        type: "textbox",
        role: "textbox",
        name: "Digit 6",
      }),
    ];

    it("detects an OTP screen", () => {
      const patterns = detectPatterns(otpNodes);
      const otp = patterns.find((p) => p.kind === "otp_screen");
      expect(otp).toBeDefined();
      expect(otp?.confidence).toBeGreaterThanOrEqual(0.8);
    });
  });

  describe("priority ordering", () => {
    const overlappingNodes: UiNode[] = [
      // Dialog (should come first in results)
      makeNode({
        id: "n_d",
        type: "dialog",
        role: "dialog",
        text: "Confirm",
      }),
      makeNode({
        id: "n_ok",
        type: "button",
        role: "button",
        text: "OK",
        clickable: true,
      }),
      // Also has error text
      makeNode({
        id: "n_err",
        type: "text",
        role: "text",
        text: "Something went wrong",
      }),
    ];

    it("prioritizes overlays over content patterns", () => {
      const patterns = detectPatterns(overlappingNodes);
      expect(patterns.length).toBeGreaterThanOrEqual(2);

      const dialogIdx = patterns.findIndex((p) => p.kind === "modal_dialog");
      const errorIdx = patterns.findIndex((p) => p.kind === "error_state");

      if (dialogIdx !== -1 && errorIdx !== -1) {
        expect(dialogIdx).toBeLessThan(errorIdx);
      }
    });
  });

  describe("no matches", () => {
    it("returns empty array for nodes with no pattern signals", () => {
      const plainNodes: UiNode[] = [
        makeNode({ id: "n_1", type: "container", text: "Hello World" }),
      ];
      const patterns = detectPatterns(plainNodes);
      expect(patterns).toHaveLength(0);
    });
  });
});
