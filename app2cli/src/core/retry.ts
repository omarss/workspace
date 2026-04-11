/**
 * Configuration for retry logic.
 */
export interface RetryOptions {
  /** Maximum number of attempts (default: 3) */
  maxAttempts?: number;
  /** Initial delay in ms between retries (default: 500) */
  initialDelayMs?: number;
  /** Exponential backoff multiplier (default: 2) */
  backoffMultiplier?: number;
  /** Maximum delay in ms (default: 10000) */
  maxDelayMs?: number;
  /** Optional predicate — only retry if this returns true for the error */
  shouldRetry?: (error: unknown) => boolean;
}

const DEFAULT_OPTIONS: Required<RetryOptions> = {
  maxAttempts: 3,
  initialDelayMs: 500,
  backoffMultiplier: 2,
  maxDelayMs: 10000,
  shouldRetry: () => true,
};

/**
 * Execute an async function with configurable retry and exponential backoff.
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  options: RetryOptions = {},
): Promise<T> {
  const opts = { ...DEFAULT_OPTIONS, ...options };
  let lastError: unknown;
  let delay = opts.initialDelayMs;

  for (let attempt = 1; attempt <= opts.maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;

      if (attempt >= opts.maxAttempts) break;
      if (!opts.shouldRetry(err)) break;

      await sleep(delay);
      delay = Math.min(delay * opts.backoffMultiplier, opts.maxDelayMs);
    }
  }

  throw lastError;
}

/**
 * Wait for a condition to become true, polling at the given interval.
 */
export async function waitFor(
  condition: () => Promise<boolean> | boolean,
  options: WaitForOptions = {},
): Promise<void> {
  const timeoutMs = options.timeoutMs ?? 10000;
  const pollIntervalMs = options.pollIntervalMs ?? 200;
  const message = options.message ?? "Condition not met within timeout";

  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const result = await condition();
    if (result) return;
    await sleep(pollIntervalMs);
  }

  throw new Error(message);
}

export interface WaitForOptions {
  /** Maximum time to wait in ms (default: 10000) */
  timeoutMs?: number;
  /** How often to check the condition in ms (default: 200) */
  pollIntervalMs?: number;
  /** Error message if timeout is reached */
  message?: string;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
