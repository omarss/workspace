import type { UiNode } from "../schema/index.js";

/**
 * An intent is a high-level user goal that maps to a concrete UI action.
 * Instead of "button named sign in", the user says "login".
 */
export interface Intent {
  /** Short name used in CLI, e.g. "login" */
  readonly name: string;
  /** Human-readable description */
  readonly description: string;
  /**
   * Resolve this intent against the current UI state.
   * Returns the target node and a confidence score, or null if not applicable.
   */
  resolve(nodes: readonly UiNode[]): IntentMatch | null;
}

export interface IntentMatch {
  /** The intent that was matched */
  intentName: string;
  /** Target node to act on */
  node: UiNode;
  /** Confidence score 0-1 */
  score: number;
  /** Action to perform: click, type, navigate */
  action: "click" | "type";
  /** For type actions, suggested input (null for click) */
  suggestedInput: string | null;
  /** Why this node was chosen */
  reason: string;
}
