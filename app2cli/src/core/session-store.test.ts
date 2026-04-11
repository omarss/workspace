import { rm } from "node:fs/promises";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { SessionStore } from "./session-store.js";

const TEST_DIR = join("artifacts", "_test_sessions");

describe("SessionStore", () => {
  let store: SessionStore;

  beforeEach(() => {
    store = new SessionStore(TEST_DIR);
  });

  afterEach(async () => {
    await rm(TEST_DIR, { recursive: true, force: true });
  });

  it("creates and retrieves a session", async () => {
    const record = await store.create("sess_1", "web", "https://example.com");
    expect(record.id).toBe("sess_1");
    expect(record.active).toBe(true);

    const retrieved = await store.get("sess_1");
    expect(retrieved).not.toBeNull();
    expect(retrieved?.target).toBe("https://example.com");
  });

  it("returns null for unknown session", async () => {
    const result = await store.get("nonexistent");
    expect(result).toBeNull();
  });

  it("lists sessions sorted by last activity", async () => {
    await store.create("sess_1", "web", "https://a.com");
    // Brief delay so timestamps differ
    await store.create("sess_2", "android", "com.example.app");

    const list = await store.list();
    expect(list).toHaveLength(2);
    // Most recent first
    expect(list[0]?.id).toBe("sess_2");
  });

  it("lists only active sessions when filtered", async () => {
    await store.create("sess_1", "web", "https://a.com");
    await store.create("sess_2", "web", "https://b.com");
    await store.deactivate("sess_1");

    const active = await store.list(true);
    expect(active).toHaveLength(1);
    expect(active[0]?.id).toBe("sess_2");
  });

  it("touches a session to update lastActivityAt", async () => {
    const original = await store.create("sess_1", "web", "https://a.com");
    const originalTime = original.lastActivityAt;

    // Small delay
    await new Promise((r) => {
      setTimeout(r, 10);
    });
    await store.touch("sess_1");

    const updated = await store.get("sess_1");
    expect(updated?.lastActivityAt).not.toBe(originalTime);
  });

  it("deactivates a session", async () => {
    await store.create("sess_1", "web", "https://a.com");
    await store.deactivate("sess_1");

    const record = await store.get("sess_1");
    expect(record?.active).toBe(false);
  });

  it("deletes a session", async () => {
    await store.create("sess_1", "web", "https://a.com");
    await store.delete("sess_1");

    const record = await store.get("sess_1");
    expect(record).toBeNull();
  });

  it("cleans up expired sessions", async () => {
    // Create a session with 1ms timeout (immediately expired)
    await store.create("sess_expired", "web", "https://a.com", 1);

    // Wait a tiny bit for it to expire
    await new Promise((r) => {
      setTimeout(r, 5);
    });

    const cleaned = await store.cleanupExpired();
    expect(cleaned).toBe(1);

    const record = await store.get("sess_expired");
    expect(record?.active).toBe(false);
  });

  it("purges old sessions", async () => {
    await store.create("sess_old", "web", "https://a.com");
    await store.create("sess_new", "web", "https://b.com");

    // Purge anything older than 1 day (nothing should be purged)
    const purged1 = await store.purgeOlderThan(24 * 60 * 60 * 1000);
    expect(purged1).toBe(0);

    // Purge anything older than 0ms (everything purged)
    const purged2 = await store.purgeOlderThan(0);
    expect(purged2).toBe(2);
  });

  it("isExpired correctly detects expired sessions", async () => {
    const record = await store.create("sess_1", "web", "https://a.com", 1);

    await new Promise((r) => {
      setTimeout(r, 5);
    });

    expect(store.isExpired(record)).toBe(true);
  });

  describe("path traversal protection", () => {
    it("rejects session IDs with path separators", async () => {
      await expect(store.create("../../package", "web", "x")).rejects.toThrow(
        "Invalid session ID",
      );
    });

    it("rejects session IDs with backslashes", async () => {
      await expect(store.create("..\\..\\package", "web", "x")).rejects.toThrow(
        "Invalid session ID",
      );
    });

    it("rejects dot-dot IDs", async () => {
      await expect(store.create("..", "web", "x")).rejects.toThrow(
        "Invalid session ID",
      );
    });

    it("rejects empty session IDs", async () => {
      await expect(store.create("", "web", "x")).rejects.toThrow(
        "must not be empty",
      );
    });

    it("rejects null bytes in session IDs", async () => {
      await expect(store.create("sess\0evil", "web", "x")).rejects.toThrow(
        "Invalid session ID",
      );
    });

    it("delete rejects traversal IDs", async () => {
      await expect(store.delete("../../package")).rejects.toThrow(
        "Invalid session ID",
      );
    });

    it("get rejects traversal IDs", async () => {
      await expect(store.get("../secret")).rejects.toThrow(
        "Invalid session ID",
      );
    });

    it("allows normal session IDs", async () => {
      const record = await store.create(
        "sess_abc123def456",
        "web",
        "https://example.com",
      );
      expect(record.id).toBe("sess_abc123def456");

      const retrieved = await store.get("sess_abc123def456");
      expect(retrieved).not.toBeNull();
    });
  });
});
