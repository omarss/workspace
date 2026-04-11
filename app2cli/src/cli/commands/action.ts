import { Command } from "commander";
import { ArtifactWriter } from "../../core/artifacts/index.js";
import type { ActionLogEntry } from "../../core/artifacts/index.js";
import { assertActionSafe } from "../../core/confidence.js";
import { tryResolveAsIntent } from "../../core/intents/index.js";
import { findNodeById, queryBestMatch } from "../../core/query/index.js";
import type { UiNode } from "../../core/schema/index.js";
import { cliState } from "../state.js";

const REDACT_PLACEHOLDER = "[REDACTED]";

/**
 * Check if a node represents a sensitive input field (password, OTP, token, etc.).
 * When true, typed input should be redacted in logs and terminal output.
 */
function isSensitiveInputNode(node: UiNode): boolean {
  const nameLC = (node.name ?? "").toLowerCase();
  const placeholderLC = (node.placeholder ?? "").toLowerCase();
  const combined = nameLC + " " + placeholderLC;

  const sensitivePatterns = [
    "password", "passcode", "secret", "pin", "otp",
    "verification code", "token", "cvv", "cvc",
    "security code", "card number",
  ];

  return sensitivePatterns.some((p) => combined.includes(p));
}

/**
 * Resolve a node ID from either a direct ID, intent, or query string.
 * Resolution order: direct ID -> intent -> query.
 * Enforces confidence policy when using --query or intent.
 */
function resolveNodeId(
  nodeIdOrNull: string | null,
  query: string | undefined,
  force: boolean,
): { nodeId: string; score: number | null; matchedBy: string | null } {
  const nodes = cliState.getNodes();

  // Direct node ID (starts with n_)
  if (
    nodeIdOrNull !== null &&
    nodeIdOrNull.startsWith("n_") &&
    (query === undefined || query.length === 0)
  ) {
    const node = findNodeById(nodes, nodeIdOrNull);
    if (node === undefined) {
      throw new Error(`Node ${nodeIdOrNull} not found`);
    }
    return { nodeId: nodeIdOrNull, score: null, matchedBy: null };
  }

  // Query or intent resolution
  const queryStr = query ?? nodeIdOrNull ?? "";
  if (queryStr.length === 0) {
    throw new Error("Either a node ID or --query is required");
  }

  // Try intent first (e.g. "login", "dismiss", "search")
  const intentMatch = tryResolveAsIntent(queryStr, nodes);
  if (intentMatch !== null) {
    const rejection = assertActionSafe(intentMatch.score, force);
    if (rejection !== null) {
      throw new Error(rejection);
    }
    return {
      nodeId: intentMatch.node.id,
      score: intentMatch.score,
      matchedBy: `intent:${intentMatch.intentName}`,
    };
  }

  // Fall back to query engine
  const match = queryBestMatch(nodes, queryStr);
  if (match === null) {
    throw new Error(`No match found for query: "${queryStr}"`);
  }

  const rejection = assertActionSafe(match.score, force);
  if (rejection !== null) {
    throw new Error(rejection);
  }

  return {
    nodeId: match.node.id,
    score: match.score,
    matchedBy: match.matchedBy,
  };
}

export function createClickCommand(): Command {
  return new Command("click")
    .description("Click/tap a UI node by ID or query")
    .argument("[node-id]", "Node ID to click (e.g. n_14)")
    .option("--query <q>", "Find target by query instead of ID")
    .option("--force", "Override confidence threshold check")
    .option("--log", "Log the action to the session artifacts")
    .option("--output <dir>", "Artifact output directory", "artifacts")
    .action(async (nodeId: string | undefined, opts: ActionOptions) => {
      const resolved = resolveNodeId(
        nodeId ?? null,
        opts.query,
        opts.force === true,
      );
      const adapter = cliState.getAdapter();
      const nodes = cliState.getNodes();

      const start = Date.now();
      let success = true;
      let error: string | null = null;

      try {
        await adapter.click(resolved.nodeId, nodes);
        process.stdout.write(`clicked: ${resolved.nodeId}\n`);
      } catch (err) {
        success = false;
        error = err instanceof Error ? err.message : String(err);
        throw err;
      } finally {
        const durationMs = Date.now() - start;

        if (opts.log === true) {
          await logAction("click", resolved.nodeId, null, durationMs, success, error, opts.output);
        }

        // Record to replay if active
        const recorder = cliState.getRecorder();
        if (recorder !== null) {
          await recorder.recordClick({
            nodeId: resolved.nodeId,
            query: opts.query,
            score: resolved.score ?? undefined,
            matchedBy: resolved.matchedBy ?? undefined,
            durationMs,
            success,
            error: error ?? undefined,
          });
        }
      }
    });
}

export function createTypeCommand(): Command {
  return new Command("type")
    .description("Type text into a UI node")
    .argument("[node-id]", "Node ID to type into (e.g. n_9)")
    .argument("<text>", "Text to type")
    .option("--query <q>", "Find target by query instead of ID")
    .option("--force", "Override confidence threshold check")
    .option("--log", "Log the action to the session artifacts")
    .option("--output <dir>", "Artifact output directory", "artifacts")
    .action(async (nodeIdOrText: string, textOrUndef: string | undefined, opts: ActionOptions) => {
      // Handle both "type <id> <text>" and "type --query <q> <text>"
      let resolved: { nodeId: string; score: number | null; matchedBy: string | null };
      let text: string;

      if (textOrUndef !== undefined) {
        // "type <node-id> <text>"
        resolved = resolveNodeId(nodeIdOrText, opts.query, opts.force === true);
        text = textOrUndef;
      } else if (opts.query !== undefined) {
        // "type --query <q> <text>" — nodeIdOrText is actually the text
        resolved = resolveNodeId(null, opts.query, opts.force === true);
        text = nodeIdOrText;
      } else {
        throw new Error("Usage: type <node-id> <text> or type --query <q> <text>");
      }

      const resolvedNodeId = resolved.nodeId;

      const adapter = cliState.getAdapter();
      const nodes = cliState.getNodes();

      // Detect if target is a sensitive field — redact input in logs/output
      const targetNode = findNodeById(nodes, resolvedNodeId);
      const sensitive = targetNode !== undefined && isSensitiveInputNode(targetNode);
      const safeText = sensitive ? REDACT_PLACEHOLDER : text;

      const start = Date.now();
      let success = true;
      let error: string | null = null;

      try {
        await adapter.type(resolvedNodeId, text, nodes);
        process.stdout.write(`typed into ${resolvedNodeId}: "${safeText}"\n`);
      } catch (err) {
        success = false;
        error = err instanceof Error ? err.message : String(err);
        throw err;
      } finally {
        const durationMs = Date.now() - start;

        if (opts.log === true) {
          await logAction("type", resolvedNodeId, safeText, durationMs, success, error, opts.output);
        }

        // Record to replay if active
        const recorder = cliState.getRecorder();
        if (recorder !== null) {
          await recorder.recordType({
            nodeId: resolvedNodeId,
            text: safeText,
            query: opts.query,
            score: resolved.score ?? undefined,
            matchedBy: resolved.matchedBy ?? undefined,
            durationMs,
            success,
            error: error ?? undefined,
          });
        }
      }
    });
}

export function createScreenshotCommand(): Command {
  return new Command("screenshot")
    .description("Take a screenshot of the current screen")
    .option("--output <dir>", "Artifact output directory", "artifacts")
    .option("--filename <name>", "Screenshot filename", "screen.png")
    .action(async (opts: ScreenshotOptions) => {
      const adapter = cliState.getAdapter();
      const sessionId = cliState.getSessionId();

      const buf = await adapter.screenshot();
      const writer = new ArtifactWriter(opts.output);
      const path = await writer.writeScreenshot(
        sessionId !== "" ? sessionId : "manual",
        buf,
        opts.filename,
      );
      process.stdout.write(`screenshot saved: ${path}\n`);
    });
}

interface ActionOptions {
  query?: string;
  force?: boolean;
  log?: boolean;
  output: string;
}

interface ScreenshotOptions {
  output: string;
  filename: string;
}

async function logAction(
  action: string,
  targetNodeId: string | null,
  input: string | null,
  durationMs: number,
  success: boolean,
  error: string | null,
  outputDir: string,
): Promise<void> {
  const sessionId = cliState.getSessionId();
  if (sessionId === "") return;

  const entry: ActionLogEntry = {
    timestamp: new Date().toISOString(),
    action,
    targetNodeId,
    input,
    durationMs,
    success,
    error,
  };

  const writer = new ArtifactWriter(outputDir);
  await writer.writeActionLog(sessionId, entry);
}
