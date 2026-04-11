import { readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Snapshot } from "../schema/index.js";
import { ArtifactWriter } from "./writer.js";
import type { ActionLogEntry } from "./writer.js";

const TEST_DIR = join("artifacts", "_test_artifacts");

describe("ArtifactWriter", () => {
  let writer: ArtifactWriter;
  const sessionId = "sess_test123";

  beforeEach(() => {
    writer = new ArtifactWriter(TEST_DIR);
  });

  afterEach(async () => {
    await rm(TEST_DIR, { recursive: true, force: true });
  });

  it("writes a screenshot and returns the path", async () => {
    const data = Buffer.from("fake-png-data");
    const path = await writer.writeScreenshot(sessionId, data);

    expect(path).toBe(join(TEST_DIR, sessionId, "screen.png"));
    const content = await readFile(path);
    expect(content.toString()).toBe("fake-png-data");
  });

  it("writes raw source and returns the path", async () => {
    const html = "<html><body>Hello</body></html>";
    const path = await writer.writeRawSource(sessionId, html);

    expect(path).toBe(join(TEST_DIR, sessionId, "source.raw"));
    const content = await readFile(path, "utf-8");
    expect(content).toBe(html);
  });

  it("writes normalized JSON and returns the path", async () => {
    const snapshot: Snapshot = {
      session: {
        id: sessionId,
        platform: "web",
        target: "https://example.com",
        timestamp: "2026-04-03T14:20:00Z",
      },
      screen: {
        title: "Test",
        url: "https://example.com",
        packageName: null,
        activity: null,
        width: 1280,
        height: 720,
      },
      nodes: [],
      patterns: [],
      semanticObjects: [],
      artifacts: {
        screenshot: null,
        rawSource: null,
        normalizedSource: null,
      },
    };

    const path = await writer.writeNormalizedSource(sessionId, snapshot);
    expect(path).toBe(join(TEST_DIR, sessionId, "source.json"));

    const content = await readFile(path, "utf-8");
    const parsed: unknown = JSON.parse(content);
    expect(parsed).toEqual(snapshot);
  });

  it("writes action log entries as JSONL", async () => {
    const entry: ActionLogEntry = {
      timestamp: "2026-04-03T14:20:00Z",
      action: "click",
      targetNodeId: "n_1",
      input: null,
      durationMs: 42,
      success: true,
      error: null,
    };

    await writer.writeActionLog(sessionId, entry);
    await writer.writeActionLog(sessionId, {
      ...entry,
      action: "type",
      input: "hello",
    });

    const content = await readFile(
      join(TEST_DIR, sessionId, "actions.jsonl"),
      "utf-8",
    );
    const lines = content.trim().split("\n");
    expect(lines).toHaveLength(2);

    const first: unknown = JSON.parse(lines[0] ?? "");
    expect(first).toMatchObject({ action: "click", targetNodeId: "n_1" });
  });

  it("writeAll creates all artifacts", async () => {
    const snapshot: Snapshot = {
      session: {
        id: sessionId,
        platform: "web",
        target: "https://example.com",
        timestamp: "2026-04-03T14:20:00Z",
      },
      screen: {
        title: "Test",
        url: "https://example.com",
        packageName: null,
        activity: null,
        width: 1280,
        height: 720,
      },
      nodes: [],
      patterns: [],
      semanticObjects: [],
      artifacts: {
        screenshot: null,
        rawSource: null,
        normalizedSource: null,
      },
    };

    const artifacts = await writer.writeAll(sessionId, {
      screenshot: Buffer.from("img"),
      rawSource: "<html></html>",
      snapshot,
    });

    expect(artifacts.screenshot).toBeTruthy();
    expect(artifacts.rawSource).toBeTruthy();
    expect(artifacts.normalizedSource).toBeTruthy();
  });

  it("writeAll handles missing optional artifacts", async () => {
    const artifacts = await writer.writeAll(sessionId, {});
    expect(artifacts.screenshot).toBeNull();
    expect(artifacts.rawSource).toBeNull();
    expect(artifacts.normalizedSource).toBeNull();
  });

  it("writeAll produces self-consistent source.json with artifact paths", async () => {
    const snapshot: Snapshot = {
      session: {
        id: sessionId,
        platform: "web",
        target: "https://example.com",
        timestamp: "2026-04-03T14:20:00Z",
      },
      screen: {
        title: "Test",
        url: "https://example.com",
        packageName: null,
        activity: null,
        width: 1280,
        height: 720,
      },
      nodes: [],
      patterns: [],
      semanticObjects: [],
      artifacts: {
        screenshot: null,
        rawSource: null,
        normalizedSource: null,
      },
    };

    const artifacts = await writer.writeAll(sessionId, {
      screenshot: Buffer.from("img"),
      rawSource: "<html></html>",
      snapshot,
    });

    // Read back the saved source.json and verify artifact paths are populated
    const savedPath = artifacts.normalizedSource;
    expect(savedPath).toBeTruthy();
    const savedContent = await readFile(
      join(TEST_DIR, sessionId, "source.json"),
      "utf-8",
    );
    const savedSnapshot = JSON.parse(savedContent) as Snapshot;
    expect(savedSnapshot.artifacts.screenshot).toBe(artifacts.screenshot);
    expect(savedSnapshot.artifacts.rawSource).toBe(artifacts.rawSource);
    // normalizedSource path is set after the JSON is written, so it shows null in the file
    // The key invariant: screenshot and rawSource paths are present in the saved JSON
  });

  it("rejects session ids that escape the artifacts root", async () => {
    await expect(
      writer.writeScreenshot("../outside", Buffer.from("img")),
    ).rejects.toThrow(/sessionId/);
  });

  it("rejects filenames that escape the session directory", async () => {
    await expect(
      writer.writeRawSource(sessionId, "<html></html>", "../source.raw"),
    ).rejects.toThrow(/filename/);
  });
});
