/**
 * Confidence policy thresholds per the design spec:
 * - >= 0.95: safe for direct interaction (click, type)
 * - 0.85-0.94: safe for query/suggestion, NOT for destructive actions
 * - < 0.85: ambiguous, must fail closed
 */

export const CONFIDENCE_ACTION_THRESHOLD = 0.95;
export const CONFIDENCE_QUERY_THRESHOLD = 0.85;

export type ConfidenceLevel = "action_safe" | "query_safe" | "ambiguous";

/**
 * Classify a confidence score into a policy level.
 */
export function classifyConfidence(score: number): ConfidenceLevel {
  if (score >= CONFIDENCE_ACTION_THRESHOLD) return "action_safe";
  if (score >= CONFIDENCE_QUERY_THRESHOLD) return "query_safe";
  return "ambiguous";
}

/**
 * Check if a confidence score is safe for executing an action.
 * Returns an error message if not safe, or null if safe.
 */
export function assertActionSafe(
  score: number,
  force: boolean,
): string | null {
  if (force) return null;

  const level = classifyConfidence(score);

  switch (level) {
    case "action_safe":
      return null;
    case "query_safe":
      return (
        `Confidence ${score.toFixed(2)} is below the action threshold (${String(CONFIDENCE_ACTION_THRESHOLD)}). ` +
        `This match is safe for querying but not for interaction. Use --force to override.`
      );
    case "ambiguous":
      return (
        `Confidence ${score.toFixed(2)} is below the minimum threshold (${String(CONFIDENCE_QUERY_THRESHOLD)}). ` +
        `The match is ambiguous. Use --force to override.`
      );
  }
}
