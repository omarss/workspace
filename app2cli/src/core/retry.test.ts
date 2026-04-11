import { describe, expect, it } from "vitest";
import { waitFor, withRetry } from "./retry.js";

describe("withRetry", () => {
  it("returns on first success", async () => {
    let calls = 0;
    const result = await withRetry(() => {
      calls++;
      return Promise.resolve("ok");
    });
    expect(result).toBe("ok");
    expect(calls).toBe(1);
  });

  it("retries on failure and succeeds", async () => {
    let calls = 0;
    const result = await withRetry(
      () => {
        calls++;
        if (calls < 3) return Promise.reject(new Error("not yet"));
        return Promise.resolve("ok");
      },
      { maxAttempts: 3, initialDelayMs: 10 },
    );
    expect(result).toBe("ok");
    expect(calls).toBe(3);
  });

  it("throws after max attempts exhausted", async () => {
    let calls = 0;
    await expect(
      withRetry(
        () => {
          calls++;
          return Promise.reject(new Error("always fails"));
        },
        { maxAttempts: 2, initialDelayMs: 10 },
      ),
    ).rejects.toThrow("always fails");
    expect(calls).toBe(2);
  });

  it("stops retrying when shouldRetry returns false", async () => {
    let calls = 0;
    await expect(
      withRetry(
        () => {
          calls++;
          return Promise.reject(new Error("fatal"));
        },
        {
          maxAttempts: 5,
          initialDelayMs: 10,
          shouldRetry: (err) =>
            err instanceof Error && !err.message.includes("fatal"),
        },
      ),
    ).rejects.toThrow("fatal");
    expect(calls).toBe(1);
  });

  it("applies exponential backoff", async () => {
    const timestamps: number[] = [];
    let calls = 0;

    await expect(
      withRetry(
        () => {
          calls++;
          timestamps.push(Date.now());
          return Promise.reject(new Error("fail"));
        },
        {
          maxAttempts: 3,
          initialDelayMs: 50,
          backoffMultiplier: 2,
        },
      ),
    ).rejects.toThrow("fail");

    expect(calls).toBe(3);
    if (timestamps.length >= 3) {
      const t0 = timestamps[0] ?? 0;
      const t1 = timestamps[1] ?? 0;
      const t2 = timestamps[2] ?? 0;
      const delay1 = t1 - t0;
      const delay2 = t2 - t1;
      expect(delay2).toBeGreaterThan(delay1 * 1.3);
    }
  });
});

describe("waitFor", () => {
  it("resolves immediately when condition is true", async () => {
    await waitFor(() => true, { timeoutMs: 1000 });
  });

  it("polls until condition becomes true", async () => {
    let count = 0;
    await waitFor(
      () => {
        count++;
        return count >= 3;
      },
      { timeoutMs: 2000, pollIntervalMs: 20 },
    );
    expect(count).toBeGreaterThanOrEqual(3);
  });

  it("throws on timeout", async () => {
    await expect(
      waitFor(() => false, {
        timeoutMs: 100,
        pollIntervalMs: 20,
        message: "timed out waiting",
      }),
    ).rejects.toThrow("timed out waiting");
  });

  it("works with async conditions", async () => {
    let count = 0;
    await waitFor(
      () => {
        count++;
        return Promise.resolve(count >= 2);
      },
      { timeoutMs: 2000, pollIntervalMs: 20 },
    );
    expect(count).toBeGreaterThanOrEqual(2);
  });
});
