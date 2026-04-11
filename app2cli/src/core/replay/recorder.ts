import { appendFile, mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { ReplaySession, ReplayStep } from "./types.js";

/**
 * Records user actions into a replay session file.
 * Writes each step as a JSONL line for streaming durability,
 * and can export the full session as a single JSON file.
 */
export class ReplayRecorder {
  private readonly session: ReplaySession;
  private readonly outputDir: string;
  private stepCount = 0;

  constructor(
    sessionId: string,
    platform: string,
    target: string,
    outputDir: string,
  ) {
    this.session = {
      sessionId,
      platform,
      target,
      startedAt: new Date().toISOString(),
      endedAt: null,
      steps: [],
    };
    this.outputDir = outputDir;
  }

  /**
   * Record a single action step.
   * Appends to the JSONL log for crash-safe persistence.
   */
  async recordStep(step: Omit<ReplayStep, "step">): Promise<ReplayStep> {
    this.stepCount++;
    const fullStep: ReplayStep = { step: this.stepCount, ...step };
    this.session.steps.push(fullStep);

    // Append to JSONL for streaming durability
    await this.appendToLog(fullStep);

    return fullStep;
  }

  /**
   * Record a click action.
   */
  async recordClick(params: RecordClickParams): Promise<ReplayStep> {
    return this.recordStep({
      timestamp: new Date().toISOString(),
      action: "click",
      targetNodeId: params.nodeId,
      input: null,
      query: params.query ?? null,
      decisionScore: params.score ?? null,
      matchedBy: params.matchedBy ?? null,
      rawLocator: params.locator ?? null,
      durationMs: params.durationMs,
      success: params.success,
      error: params.error ?? null,
      screenshotBefore: params.screenshotBefore ?? null,
      screenshotAfter: params.screenshotAfter ?? null,
    });
  }

  /**
   * Record a type action.
   */
  async recordType(params: RecordTypeParams): Promise<ReplayStep> {
    return this.recordStep({
      timestamp: new Date().toISOString(),
      action: "type",
      targetNodeId: params.nodeId,
      input: params.text,
      query: params.query ?? null,
      decisionScore: params.score ?? null,
      matchedBy: params.matchedBy ?? null,
      rawLocator: params.locator ?? null,
      durationMs: params.durationMs,
      success: params.success,
      error: params.error ?? null,
      screenshotBefore: params.screenshotBefore ?? null,
      screenshotAfter: params.screenshotAfter ?? null,
    });
  }

  /**
   * Record a navigation action (page load, app launch).
   */
  async recordNavigate(params: RecordNavigateParams): Promise<ReplayStep> {
    return this.recordStep({
      timestamp: new Date().toISOString(),
      action: "navigate",
      targetNodeId: null,
      input: params.url,
      query: null,
      decisionScore: null,
      matchedBy: null,
      rawLocator: null,
      durationMs: params.durationMs,
      success: params.success,
      error: params.error ?? null,
      screenshotBefore: null,
      screenshotAfter: params.screenshotAfter ?? null,
    });
  }

  /**
   * Finalize the session and write the complete session JSON.
   */
  async finalize(): Promise<string> {
    this.session.endedAt = new Date().toISOString();

    const dir = await this.ensureDir();
    const sessionPath = join(dir, "replay.json");
    await writeFile(
      sessionPath,
      JSON.stringify(this.session, null, 2),
      "utf-8",
    );

    return sessionPath;
  }

  /**
   * Get the current session state (for inspection).
   */
  getSession(): Readonly<ReplaySession> {
    return this.session;
  }

  private async appendToLog(step: ReplayStep): Promise<void> {
    const dir = await this.ensureDir();
    const logPath = join(dir, "replay.jsonl");
    await appendFile(logPath, JSON.stringify(step) + "\n", "utf-8");
  }

  private async ensureDir(): Promise<string> {
    const dir = join(this.outputDir, this.session.sessionId);
    await mkdir(dir, { recursive: true });
    return dir;
  }
}

interface RecordClickParams {
  nodeId: string;
  query?: string;
  score?: number;
  matchedBy?: string;
  locator?: string;
  durationMs: number;
  success: boolean;
  error?: string;
  screenshotBefore?: string;
  screenshotAfter?: string;
}

interface RecordTypeParams {
  nodeId: string;
  text: string;
  query?: string;
  score?: number;
  matchedBy?: string;
  locator?: string;
  durationMs: number;
  success: boolean;
  error?: string;
  screenshotBefore?: string;
  screenshotAfter?: string;
}

interface RecordNavigateParams {
  url: string;
  durationMs: number;
  success: boolean;
  error?: string;
  screenshotAfter?: string;
}
