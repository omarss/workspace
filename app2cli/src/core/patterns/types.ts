import type { PatternEvidence, PatternKind, PatternMatch, UiNode } from "../schema/index.js";

/**
 * Interface for a single pattern detector.
 * Each detector evaluates the UI node tree for one pattern kind
 * using deterministic scoring rules.
 */
export interface PatternDetector {
  /** The pattern kind this detector identifies */
  readonly kind: PatternKind;

  /** Evaluate nodes and return a match (or null if pattern not found) */
  detect(nodes: readonly UiNode[]): PatternMatch | null;
}

/**
 * Helper to build a PatternMatch with proper ID generation.
 */
export function buildMatch(
  kind: PatternKind,
  confidence: number,
  evidence: PatternEvidence,
  counter: number,
): PatternMatch {
  return {
    id: `pat_${kind}_${String(counter)}`,
    kind,
    confidence: Math.round(confidence * 100) / 100,
    evidence,
  };
}

/**
 * Count how many nodes match a predicate.
 */
export function countMatching(
  nodes: readonly UiNode[],
  predicate: (node: UiNode) => boolean,
): number {
  return nodes.filter(predicate).length;
}

/**
 * Find nodes matching a predicate.
 */
export function findMatching(
  nodes: readonly UiNode[],
  predicate: (node: UiNode) => boolean,
): UiNode[] {
  return nodes.filter(predicate);
}

/**
 * Check if a node's text or name matches any of the given patterns (case-insensitive).
 */
export function textMatches(node: UiNode, patterns: readonly string[]): boolean {
  const text = node.text.toLowerCase();
  const name = (node.name ?? "").toLowerCase();
  return patterns.some((p) => text.includes(p) || name.includes(p));
}

/**
 * Check if a node is an input/textbox type.
 */
export function isInputNode(node: UiNode): boolean {
  const inputTypes = new Set(["textbox", "input", "edittext", "searchbox"]);
  return inputTypes.has(node.type) || inputTypes.has(node.role);
}

/**
 * Check if a node is a button/action type.
 */
export function isButtonNode(node: UiNode): boolean {
  const buttonTypes = new Set(["button", "submit"]);
  return (
    buttonTypes.has(node.type) ||
    buttonTypes.has(node.role) ||
    (node.clickable && node.type === "link")
  );
}
