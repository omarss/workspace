import { appendFile, mkdir, writeFile } from "node:fs/promises";
import { isAbsolute, join, relative, resolve } from "node:path";
import type { RedactConfig } from "../redact.js";
import { redactObject, redactString } from "../redact.js";
import type { Artifacts, Snapshot } from "../schema/index.js";

/** Default root directory for artifact storage. */
const DEFAULT_ARTIFACTS_DIR = "artifacts";

/**
 * Options for the artifact writer.
 */
export interface ArtifactWriterOptions {
  /** Root directory for artifact storage */
  rootDir?: string;
  /** Redaction config — when set, sensitive data is redacted before writing */
  redact?: RedactConfig;
}

/**
 * Manages writing artifacts (screenshots, raw source, normalized JSON)
 * to per-session directories on disk.
 */
export class ArtifactWriter {
  private readonly rootDir: string;
  private readonly resolvedRootDir: string;
  private readonly redactConfig: RedactConfig | undefined;

  constructor(rootDirOrOptions?: string | ArtifactWriterOptions) {
    if (typeof rootDirOrOptions === "string" || rootDirOrOptions === undefined) {
      this.rootDir = rootDirOrOptions ?? DEFAULT_ARTIFACTS_DIR;
      this.redactConfig = undefined;
    } else {
      this.rootDir = rootDirOrOptions.rootDir ?? DEFAULT_ARTIFACTS_DIR;
      this.redactConfig = rootDirOrOptions.redact;
    }
    this.resolvedRootDir = resolve(this.rootDir);
  }

  /**
   * Ensure the session-scoped artifact directory exists.
   */
  private async ensureSessionDir(sessionId: string): Promise<ResolvedPath> {
    const safeSessionId = assertSafePathSegment(sessionId, "sessionId");
    const relativePath = join(this.rootDir, safeSessionId);
    const resolvedPath = resolve(relativePath);
    assertWithinRoot(
      this.resolvedRootDir,
      resolvedPath,
      "Session directory",
    );
    await mkdir(resolvedPath, { recursive: true });
    return { relativePath, resolvedPath };
  }

  /**
   * Resolve a safe artifact file path under the session directory.
   */
  private async resolveArtifactPath(
    sessionId: string,
    filename: string,
  ): Promise<ResolvedPath> {
    const dir = await this.ensureSessionDir(sessionId);
    const safeFilename = assertSafePathSegment(filename, "filename");
    const relativePath = join(dir.relativePath, safeFilename);
    const resolvedPath = resolve(dir.resolvedPath, safeFilename);
    assertWithinRoot(this.resolvedRootDir, resolvedPath, "Artifact path");
    return { relativePath, resolvedPath };
  }

  /**
   * Write a screenshot image to the session directory.
   */
  async writeScreenshot(
    sessionId: string,
    data: Buffer,
    filename = "screen.png",
  ): Promise<string> {
    const filePath = await this.resolveArtifactPath(sessionId, filename);
    await writeFile(filePath.resolvedPath, data);
    return filePath.relativePath;
  }

  /**
   * Write raw source (HTML or XML) to the session directory.
   */
  async writeRawSource(
    sessionId: string,
    source: string,
    filename = "source.raw",
  ): Promise<string> {
    const filePath = await this.resolveArtifactPath(sessionId, filename);
    const data =
      this.redactConfig !== undefined
        ? redactString(source, this.redactConfig)
        : source;
    await writeFile(filePath.resolvedPath, data, "utf-8");
    return filePath.relativePath;
  }

  /**
   * Write the normalized snapshot JSON to the session directory.
   */
  async writeNormalizedSource(
    sessionId: string,
    snapshot: Snapshot,
    filename = "source.json",
  ): Promise<string> {
    const filePath = await this.resolveArtifactPath(sessionId, filename);
    const data =
      this.redactConfig !== undefined
        ? redactObject(snapshot, this.redactConfig)
        : snapshot;
    await writeFile(
      filePath.resolvedPath,
      JSON.stringify(data, null, 2),
      "utf-8",
    );
    return filePath.relativePath;
  }

  /**
   * Write an action log entry to the session directory.
   * Appends to an existing log file.
   */
  async writeActionLog(
    sessionId: string,
    entry: ActionLogEntry,
    filename = "actions.jsonl",
  ): Promise<string> {
    const filePath = await this.resolveArtifactPath(sessionId, filename);
    const data =
      this.redactConfig !== undefined
        ? redactObject(entry, this.redactConfig)
        : entry;
    const line = JSON.stringify(data) + "\n";
    await appendFile(filePath.resolvedPath, line, "utf-8");
    return filePath.relativePath;
  }

  /**
   * Write all artifacts for a snapshot and return the artifact paths.
   *
   * Writes screenshot and raw source first, then populates the snapshot's
   * artifact paths before writing the normalized JSON. This ensures
   * source.json is self-consistent with the actual artifact locations.
   */
  async writeAll(
    sessionId: string,
    options: WriteAllOptions,
  ): Promise<Artifacts> {
    // Step 1: write screenshot and raw source concurrently
    const [screenshotPath, rawSourcePath] = await Promise.all([
      options.screenshot !== undefined
        ? this.writeScreenshot(sessionId, options.screenshot)
        : Promise.resolve(null),
      options.rawSource !== undefined
        ? this.writeRawSource(sessionId, options.rawSource)
        : Promise.resolve(null),
    ]);

    const artifacts: Artifacts = {
      screenshot: screenshotPath,
      rawSource: rawSourcePath,
      normalizedSource: null,
    };

    // Step 2: update snapshot artifact paths, then write normalized JSON
    if (options.snapshot !== undefined) {
      options.snapshot.artifacts = artifacts;
      const normalizedPath = await this.writeNormalizedSource(
        sessionId,
        options.snapshot,
      );
      artifacts.normalizedSource = normalizedPath;
    }

    return artifacts;
  }
}

/**
 * A single action log entry for audit trails.
 */
export interface ActionLogEntry {
  timestamp: string;
  action: string;
  targetNodeId: string | null;
  input: string | null;
  durationMs: number;
  success: boolean;
  error: string | null;
}

/**
 * Options for writing all artifacts at once.
 */
interface WriteAllOptions {
  screenshot?: Buffer;
  rawSource?: string;
  snapshot?: Snapshot;
}

interface ResolvedPath {
  relativePath: string;
  resolvedPath: string;
}

function assertSafePathSegment(value: string, label: string): string {
  if (value.trim().length === 0) {
    throw new Error(`${label} must not be empty`);
  }

  if (
    value === "." ||
    value === ".." ||
    value.includes("/") ||
    value.includes("\\") ||
    value.includes("\0")
  ) {
    throw new Error(`${label} must be a single safe path segment`);
  }

  return value;
}

function assertWithinRoot(
  rootDir: string,
  candidatePath: string,
  label: string,
): void {
  const relativeCandidate = relative(rootDir, candidatePath);
  if (
    relativeCandidate === "" ||
    (!relativeCandidate.startsWith("..") &&
      !isAbsolute(relativeCandidate))
  ) {
    return;
  }

  throw new Error(`${label} must stay within the artifacts root`);
}
