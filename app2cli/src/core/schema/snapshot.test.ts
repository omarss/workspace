import { describe, expect, it } from "vitest";
import { SnapshotSchema } from "./snapshot.js";

describe("SnapshotSchema", () => {
  const validSnapshot = {
    session: {
      id: "sess_123",
      platform: "web" as const,
      target: "https://example.com",
      timestamp: "2026-04-03T14:20:00Z",
    },
    screen: {
      title: "Login",
      url: "https://example.com/login",
      packageName: null,
      activity: null,
      width: 1280,
      height: 720,
    },
    nodes: [
      {
        id: "n_1",
        type: "button",
        role: "button",
        text: "Sign in",
        name: "Sign in",
        description: null,
        value: null,
        placeholder: null,
        enabled: true,
        visible: true,
        clickable: true,
        focusable: true,
        checked: null,
        selected: false,
        bounds: { x: 640, y: 410, width: 180, height: 48 },
        locator: { web: { css: "button[type='submit']" } },
        path: ["root", "main", "form", "button[1]"],
        children: [],
      },
    ],
    patterns: [
      {
        id: "pat_login_1",
        kind: "login_form" as const,
        confidence: 0.97,
        evidence: {
          fields: ["n_2", "n_3"],
          actions: ["n_1"],
          texts: ["Sign in"],
        },
      },
    ],
    semanticObjects: [
      {
        id: "obj_1",
        kind: "form",
        label: "Login",
        nodeIds: ["n_1"],
        properties: {},
      },
    ],
    artifacts: {
      screenshot: "artifacts/sess_123/screen.png",
      rawSource: "artifacts/sess_123/source.raw",
      normalizedSource: "artifacts/sess_123/source.json",
    },
  };

  it("validates a complete snapshot", () => {
    const result = SnapshotSchema.safeParse(validSnapshot);
    expect(result.success).toBe(true);
  });

  it("validates a snapshot with empty nodes and patterns", () => {
    const result = SnapshotSchema.safeParse({
      ...validSnapshot,
      nodes: [],
      patterns: [],
    });
    expect(result.success).toBe(true);
  });

  it("rejects invalid platform", () => {
    const result = SnapshotSchema.safeParse({
      ...validSnapshot,
      session: { ...validSnapshot.session, platform: "ios" },
    });
    expect(result.success).toBe(false);
  });

  it("rejects pattern with out-of-range confidence", () => {
    const result = SnapshotSchema.safeParse({
      ...validSnapshot,
      patterns: [
        {
          ...validSnapshot.patterns[0],
          confidence: 1.5,
        },
      ],
    });
    expect(result.success).toBe(false);
  });

  it("rejects missing session", () => {
    const { session: _, ...noSession } = validSnapshot;
    const result = SnapshotSchema.safeParse(noSession);
    expect(result.success).toBe(false);
  });
});
