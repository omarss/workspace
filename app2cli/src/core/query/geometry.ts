import type { Bounds, UiNode } from "../schema/index.js";

/**
 * Spatial relationship between two UI nodes.
 */
export type SpatialRelation = "above" | "below" | "left" | "right" | "nearest";

/**
 * Result of a geometry query.
 */
export interface GeometryMatch {
  node: UiNode;
  distance: number;
  relation: SpatialRelation;
}

/**
 * Find nodes spatially related to a reference node.
 *
 * Supports:
 * - "nearest <role> to <ref>"
 * - "<role> below <ref>"
 * - "<role> above <ref>"
 * - "<role> left of <ref>"
 * - "<role> right of <ref>"
 */
export function findByGeometry(
  nodes: readonly UiNode[],
  referenceId: string,
  relation: SpatialRelation,
  filter?: (node: UiNode) => boolean,
): GeometryMatch[] {
  const ref = nodes.find((n) => n.id === referenceId);
  const refBounds = ref?.bounds;
  if (refBounds === undefined || refBounds === null) return [];

  const refCenter = boundsCenter(refBounds);
  const matches: GeometryMatch[] = [];

  for (const node of nodes) {
    if (node.id === referenceId) continue;
    if (node.bounds === null) continue;
    if (!node.visible) continue;
    if (filter !== undefined && !filter(node)) continue;

    const nodeCenter = boundsCenter(node.bounds);

    if (relation === "nearest") {
      matches.push({
        node,
        distance: euclideanDistance(refCenter, nodeCenter),
        relation: "nearest",
      });
    } else if (matchesRelation(refCenter, nodeCenter, relation)) {
      matches.push({
        node,
        distance: euclideanDistance(refCenter, nodeCenter),
        relation,
      });
    }
  }

  matches.sort((a, b) => a.distance - b.distance);
  return matches;
}

/**
 * Find the nearest node matching a filter to a reference node.
 */
export function findNearest(
  nodes: readonly UiNode[],
  referenceId: string,
  filter?: (node: UiNode) => boolean,
): GeometryMatch | null {
  const matches = findByGeometry(nodes, referenceId, "nearest", filter);
  return matches[0] ?? null;
}

/**
 * Parse a geometry query string.
 *
 * Patterns:
 * - "nearest button to n_5"
 * - "button below n_3"
 * - "input above n_7"
 * - "link right of n_2"
 */
export function parseGeometryQuery(
  query: string,
): GeometryQuery | null {
  const normalized = query.trim().toLowerCase();

  // "nearest <role> to <ref>"
  const nearestMatch = /^nearest\s+(\w+)\s+to\s+(n_\S+)$/.exec(normalized);
  if (nearestMatch !== null) {
    return {
      relation: "nearest",
      role: nearestMatch[1] ?? "",
      referenceId: nearestMatch[2] ?? "",
    };
  }

  // "<role> below|above|left of|right of <ref>"
  const relMatch =
    /^(\w+)\s+(below|above|left of|right of)\s+(n_\S+)$/.exec(normalized);
  if (relMatch !== null) {
    const dirStr = relMatch[2] ?? "";
    const relation = dirStr === "left of"
      ? "left"
      : dirStr === "right of"
        ? "right"
        : (dirStr as SpatialRelation);

    return {
      relation,
      role: relMatch[1] ?? "",
      referenceId: relMatch[3] ?? "",
    };
  }

  return null;
}

export interface GeometryQuery {
  relation: SpatialRelation;
  role: string;
  referenceId: string;
}

// ---- Helpers ----

interface Point {
  x: number;
  y: number;
}

function boundsCenter(bounds: Bounds): Point {
  return {
    x: bounds.x + bounds.width / 2,
    y: bounds.y + bounds.height / 2,
  };
}

function euclideanDistance(a: Point, b: Point): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

function matchesRelation(
  ref: Point,
  candidate: Point,
  relation: SpatialRelation,
): boolean {
  switch (relation) {
    case "below":
      return candidate.y > ref.y;
    case "above":
      return candidate.y < ref.y;
    case "left":
      return candidate.x < ref.x;
    case "right":
      return candidate.x > ref.x;
    case "nearest":
      return true;
  }
}
