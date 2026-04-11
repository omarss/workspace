/**
 * A recorded action step with full provenance for deterministic replay.
 */
export interface ReplayStep {
  /** Step sequence number (1-based) */
  step: number;
  /** ISO 8601 timestamp when the action was executed */
  timestamp: string;
  /** Action type: click, type, inspect, screenshot, navigate */
  action: string;
  /** Target node ID (null for non-targeted actions) */
  targetNodeId: string | null;
  /** Input text (for type actions) or URL (for navigate actions) */
  input: string | null;
  /** The query string used to find the target (if query-based) */
  query: string | null;
  /** Confidence score of the match decision */
  decisionScore: number | null;
  /** How the target was resolved: exact_id, role_and_name, fuzzy_text, etc. */
  matchedBy: string | null;
  /** Raw selector/locator used for the action */
  rawLocator: string | null;
  /** Duration of the action in milliseconds */
  durationMs: number;
  /** Whether the action succeeded */
  success: boolean;
  /** Error message if action failed */
  error: string | null;
  /** Path to screenshot taken before the action (if configured) */
  screenshotBefore: string | null;
  /** Path to screenshot taken after the action (if configured) */
  screenshotAfter: string | null;
}

/**
 * A complete replay session — a sequence of steps with session metadata.
 */
export interface ReplaySession {
  /** Session ID */
  sessionId: string;
  /** Platform: web or android */
  platform: string;
  /** Target URL or package name */
  target: string;
  /** ISO 8601 timestamp when recording started */
  startedAt: string;
  /** ISO 8601 timestamp when recording ended */
  endedAt: string | null;
  /** Ordered list of recorded steps */
  steps: ReplayStep[];
}
