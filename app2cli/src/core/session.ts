import type { Platform, Session } from "./schema/index.js";

/**
 * Generate a unique session ID with a "sess_" prefix.
 * Uses crypto.randomUUID() for unique, collision-resistant IDs.
 */
export function generateSessionId(): string {
  const uuid = globalThis.crypto.randomUUID();
  return `sess_${uuid.replaceAll("-", "")}`;
}

/**
 * Create a new session object for the given platform and target.
 */
export function createSession(platform: Platform, target: string): Session {
  return {
    id: generateSessionId(),
    platform,
    target,
    timestamp: new Date().toISOString(),
  };
}
