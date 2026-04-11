import { createHash } from "node:crypto";
import type { UiNode } from "./schema/index.js";

/**
 * Generate a stable, deterministic node ID based on structural attributes.
 *
 * The ID survives page refreshes as long as the element's structural
 * position and key attributes remain the same. Uses a short hash of:
 * - role
 * - tag/type
 * - accessible name
 * - text content (first 50 chars)
 * - path in tree
 * - resource ID or CSS selector
 *
 * Falls back to sequential ID if the hash collides.
 */
export function generateStableId(
  attributes: StableIdAttributes,
  index: number,
): string {
  const parts = [
    attributes.role,
    attributes.type,
    attributes.name ?? "",
    (attributes.text ?? "").slice(0, 50),
    attributes.path.join("/"),
    attributes.locatorKey ?? "",
  ];

  const input = parts.join("|");
  const hash = createHash("sha256").update(input).digest("hex").slice(0, 8);
  return `n_${hash}_${String(index)}`;
}

/**
 * Attributes used for stable ID generation.
 */
export interface StableIdAttributes {
  role: string;
  type: string;
  name: string | null;
  text: string | null;
  path: string[];
  locatorKey: string | null;
}

/**
 * Reassign stable IDs to a flat array of UiNodes.
 * Updates both node.id and all children references.
 */
export function assignStableIds(nodes: UiNode[]): UiNode[] {
  // Build old ID -> new ID mapping
  const idMap = new Map<string, string>();

  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i];
    if (node === undefined) continue;

    const locatorKey =
      node.locator.web?.css ??
      node.locator.android?.resourceId ??
      null;

    const newId = generateStableId(
      {
        role: node.role,
        type: node.type,
        name: node.name,
        text: node.text,
        path: node.path,
        locatorKey,
      },
      i,
    );

    idMap.set(node.id, newId);
  }

  // Remap all IDs and children references
  return nodes.map((node) => ({
    ...node,
    id: idMap.get(node.id) ?? node.id,
    children: node.children.map((childId) => idMap.get(childId) ?? childId),
  }));
}
