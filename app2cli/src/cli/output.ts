import type { PatternMatch, Snapshot, UiNode } from "../core/schema/index.js";
import type { QueryMatch } from "../core/query/index.js";
import type { SemanticObject } from "../core/semantic/index.js";

/**
 * Format a list of UI nodes for terminal display.
 */
export function formatNodeList(nodes: readonly UiNode[]): string {
  const lines: string[] = [];
  for (const node of nodes) {
    if (!node.visible) continue;
    const parts = [
      `[${node.id}]`,
      node.type.padEnd(12),
      `"${truncate(node.text.length > 0 ? node.text : (node.name ?? ""), 30)}"`.padEnd(34),
    ];

    const flags: string[] = [];
    if (node.clickable) flags.push("clickable");
    if (node.enabled) flags.push("enabled");
    if (node.focusable) flags.push("focusable");
    if (flags.length > 0) parts.push(flags.join(" "));

    lines.push(parts.join(" "));
  }
  return lines.join("\n");
}

/**
 * Format query results for terminal display.
 */
export function formatQueryResults(matches: readonly QueryMatch[]): string {
  if (matches.length === 0) return "no matches found";

  const lines: string[] = [];
  for (const match of matches) {
    const n = match.node;
    lines.push(
      [
        `match: ${n.id}`,
        `score: ${match.score.toFixed(2)}`,
        `matched_by: ${match.matchedBy}`,
        `type: ${n.type}`,
        `text: ${n.text.length > 0 ? n.text : (n.name ?? "(empty)")}`,
        n.bounds !== null
          ? `bounds: ${String(n.bounds.x)},${String(n.bounds.y)} ${String(n.bounds.width)}x${String(n.bounds.height)}`
          : "",
      ]
        .filter((s) => s.length > 0)
        .join("\n  "),
    );
  }
  return lines.join("\n---\n");
}

/**
 * Format detected patterns for terminal display.
 */
export function formatPatterns(patterns: readonly PatternMatch[]): string {
  if (patterns.length === 0) return "no patterns detected";

  const lines: string[] = [];
  for (const p of patterns) {
    lines.push(
      `[${p.id}] ${p.kind} (confidence: ${p.confidence.toFixed(2)})`,
    );
    if (p.evidence.fields !== undefined && p.evidence.fields.length > 0) {
      lines.push(`  fields: ${p.evidence.fields.join(", ")}`);
    }
    if (p.evidence.actions !== undefined && p.evidence.actions.length > 0) {
      lines.push(`  actions: ${p.evidence.actions.join(", ")}`);
    }
    if (p.evidence.items !== undefined && p.evidence.items.length > 0) {
      lines.push(`  items: ${p.evidence.items.join(", ")}`);
    }
  }
  return lines.join("\n");
}

/**
 * Format semantic objects for terminal display.
 */
export function formatSemanticObjects(
  objects: readonly SemanticObject[],
): string {
  if (objects.length === 0) return "no semantic objects detected";

  const lines: string[] = [];
  for (const obj of objects) {
    lines.push(`[${obj.id}] ${obj.kind}: "${obj.label}"`);
    if (obj.nodeIds.length > 0) {
      lines.push(`  nodes: ${obj.nodeIds.join(", ")}`);
    }
  }
  return lines.join("\n");
}

/**
 * Format a full snapshot as JSON.
 */
export function formatSnapshotJson(snapshot: Snapshot): string {
  return JSON.stringify(snapshot, null, 2);
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 3) + "...";
}
