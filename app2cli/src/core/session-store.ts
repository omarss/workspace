import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { join, resolve, relative, isAbsolute } from "node:path";

/**
 * Persisted session record — stored as JSON in the sessions directory.
 */
export interface SessionRecord {
  id: string;
  platform: "web" | "android";
  target: string;
  createdAt: string;
  lastActivityAt: string;
  /** Timeout in ms after which the session is considered expired */
  timeoutMs: number;
  /** Whether this session is still active */
  active: boolean;
}

const DEFAULT_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

/**
 * Manages session persistence and lifecycle.
 * Sessions are stored as individual JSON files in a directory.
 */
export class SessionStore {
  private readonly dir: string;

  constructor(dir = ".app2cli/sessions") {
    this.dir = dir;
  }

  /**
   * Create and persist a new session.
   */
  async create(
    id: string,
    platform: "web" | "android",
    target: string,
    timeoutMs = DEFAULT_TIMEOUT_MS,
  ): Promise<SessionRecord> {
    const now = new Date().toISOString();
    const record: SessionRecord = {
      id,
      platform,
      target,
      createdAt: now,
      lastActivityAt: now,
      timeoutMs,
      active: true,
    };

    await this.save(record);
    return record;
  }

  /**
   * Update the last activity timestamp for a session (touch).
   */
  async touch(id: string): Promise<void> {
    const record = await this.get(id);
    if (record === null) return;
    record.lastActivityAt = new Date().toISOString();
    await this.save(record);
  }

  /**
   * Mark a session as inactive.
   */
  async deactivate(id: string): Promise<void> {
    const record = await this.get(id);
    if (record === null) return;
    record.active = false;
    await this.save(record);
  }

  /**
   * Get a session by ID.
   */
  async get(id: string): Promise<SessionRecord | null> {
    const filePath = this.safeFilePath(id);
    try {
      const data = await readFile(filePath, "utf-8");
      return JSON.parse(data) as SessionRecord;
    } catch {
      return null;
    }
  }

  /**
   * List all sessions, optionally filtering by active status.
   */
  async list(activeOnly = false): Promise<SessionRecord[]> {
    await this.ensureDir();
    let files: string[];
    try {
      files = await readdir(this.dir);
    } catch {
      return [];
    }

    const records: SessionRecord[] = [];
    for (const file of files) {
      if (!file.endsWith(".json")) continue;
      try {
        const data = await readFile(join(this.dir, file), "utf-8");
        const record = JSON.parse(data) as SessionRecord;
        if (!activeOnly || record.active) {
          records.push(record);
        }
      } catch {
        // Corrupted session file — skip
      }
    }

    // Sort by most recent activity
    records.sort((a, b) =>
      new Date(b.lastActivityAt).getTime() - new Date(a.lastActivityAt).getTime(),
    );
    return records;
  }

  /**
   * Delete a session record.
   */
  async delete(id: string): Promise<void> {
    const filePath = this.safeFilePath(id);
    try {
      await rm(filePath, { force: true });
    } catch {
      // Ignore if file doesn't exist
    }
  }

  /**
   * Clean up expired sessions.
   * Returns the number of sessions cleaned up.
   */
  async cleanupExpired(): Promise<number> {
    const all = await this.list();
    const now = Date.now();
    let cleaned = 0;

    for (const record of all) {
      if (!record.active) continue;

      const lastActivity = new Date(record.lastActivityAt).getTime();
      if (now - lastActivity > record.timeoutMs) {
        record.active = false;
        await this.save(record);
        cleaned++;
      }
    }

    return cleaned;
  }

  /**
   * Delete all session records older than the given age in ms.
   */
  async purgeOlderThan(maxAgeMs: number): Promise<number> {
    const all = await this.list();
    const now = Date.now();
    let purged = 0;

    for (const record of all) {
      const created = new Date(record.createdAt).getTime();
      if (now - created > maxAgeMs) {
        await this.delete(record.id);
        purged++;
      }
    }

    return purged;
  }

  /**
   * Check if a session is expired.
   */
  isExpired(record: SessionRecord): boolean {
    const lastActivity = new Date(record.lastActivityAt).getTime();
    return Date.now() - lastActivity > record.timeoutMs;
  }

  private async save(record: SessionRecord): Promise<void> {
    await this.ensureDir();
    await writeFile(
      this.safeFilePath(record.id),
      JSON.stringify(record, null, 2),
      "utf-8",
    );
  }

  /**
   * Validate a session ID and return the safe file path.
   * Rejects path traversal attempts, empty IDs, and special characters.
   */
  private safeFilePath(id: string): string {
    if (id.trim().length === 0) {
      throw new Error("Session ID must not be empty");
    }
    if (
      id === "." ||
      id === ".." ||
      id.includes("/") ||
      id.includes("\\") ||
      id.includes("\0")
    ) {
      throw new Error(
        `Invalid session ID: "${id}". Must be a single safe path segment.`,
      );
    }

    const candidate = resolve(join(this.dir, `${id}.json`));
    const root = resolve(this.dir);
    const rel = relative(root, candidate);

    // rel must be non-empty, not start with "..", and not be absolute
    if (rel === "" || rel.startsWith("..") || isAbsolute(rel)) {
      throw new Error(
        `Session ID "${id}" would escape the session directory`,
      );
    }

    return candidate;
  }

  private async ensureDir(): Promise<void> {
    await mkdir(this.dir, { recursive: true });
  }
}
