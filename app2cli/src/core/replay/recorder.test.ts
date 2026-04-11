import { readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ReplayRecorder } from "./recorder.js";
import type { ReplaySession, ReplayStep } from "./types.js";

const TEST_DIR = join("artifacts", "_test_replay");

describe("ReplayRecorder", () => {
  let recorder: ReplayRecorder;
  const sessionId = "sess_replay_test";

  beforeEach(() => {
    recorder = new ReplayRecorder(sessionId, "web", "https://example.com", TEST_DIR);
  });

  afterEach(async () => {
    await rm(TEST_DIR, { recursive: true, force: true });
  });

  it("records click actions with full provenance", async () => {
    const step = await recorder.recordClick({
      nodeId: "n_1",
      query: "button named sign in",
      score: 0.98,
      matchedBy: "role_and_name",
      locator: "button[type=\"submit\"]",
      durationMs: 42,
      success: true,
    });

    expect(step.step).toBe(1);
    expect(step.action).toBe("click");
    expect(step.targetNodeId).toBe("n_1");
    expect(step.decisionScore).toBe(0.98);
    expect(step.matchedBy).toBe("role_and_name");
    expect(step.success).toBe(true);
  });

  it("records type actions", async () => {
    const step = await recorder.recordType({
      nodeId: "n_2",
      text: "test@example.com",
      query: "field labeled email",
      durationMs: 100,
      success: true,
    });

    expect(step.action).toBe("type");
    expect(step.input).toBe("test@example.com");
  });

  it("records navigate actions", async () => {
    const step = await recorder.recordNavigate({
      url: "https://example.com/login",
      durationMs: 1500,
      success: true,
    });

    expect(step.action).toBe("navigate");
    expect(step.input).toBe("https://example.com/login");
    expect(step.targetNodeId).toBeNull();
  });

  it("increments step numbers", async () => {
    await recorder.recordClick({
      nodeId: "n_1",
      durationMs: 10,
      success: true,
    });
    const step2 = await recorder.recordClick({
      nodeId: "n_2",
      durationMs: 20,
      success: true,
    });

    expect(step2.step).toBe(2);
  });

  it("persists steps to JSONL file", async () => {
    await recorder.recordClick({
      nodeId: "n_1",
      durationMs: 10,
      success: true,
    });
    await recorder.recordType({
      nodeId: "n_2",
      text: "hello",
      durationMs: 20,
      success: true,
    });

    const logPath = join(TEST_DIR, sessionId, "replay.jsonl");
    const content = await readFile(logPath, "utf-8");
    const lines = content.trim().split("\n");
    expect(lines).toHaveLength(2);

    const firstStep = JSON.parse(lines[0] ?? "") as ReplayStep;
    expect(firstStep.action).toBe("click");
    expect(firstStep.step).toBe(1);
  });

  it("finalizes session and writes complete JSON", async () => {
    await recorder.recordClick({
      nodeId: "n_1",
      durationMs: 10,
      success: true,
    });

    const path = await recorder.finalize();
    const content = await readFile(path, "utf-8");
    const session = JSON.parse(content) as ReplaySession;

    expect(session.sessionId).toBe(sessionId);
    expect(session.platform).toBe("web");
    expect(session.target).toBe("https://example.com");
    expect(session.startedAt).toBeTruthy();
    expect(session.endedAt).toBeTruthy();
    expect(session.steps).toHaveLength(1);
  });

  it("records errors in failed steps", async () => {
    const step = await recorder.recordClick({
      nodeId: "n_999",
      durationMs: 5,
      success: false,
      error: "Node n_999 not found",
    });

    expect(step.success).toBe(false);
    expect(step.error).toBe("Node n_999 not found");
  });

  it("records screenshot paths", async () => {
    const step = await recorder.recordClick({
      nodeId: "n_1",
      durationMs: 50,
      success: true,
      screenshotBefore: "before.png",
      screenshotAfter: "after.png",
    });

    expect(step.screenshotBefore).toBe("before.png");
    expect(step.screenshotAfter).toBe("after.png");
  });

  it("getSession returns current state", async () => {
    await recorder.recordClick({
      nodeId: "n_1",
      durationMs: 10,
      success: true,
    });

    const session = recorder.getSession();
    expect(session.steps).toHaveLength(1);
    expect(session.endedAt).toBeNull();
  });
});
