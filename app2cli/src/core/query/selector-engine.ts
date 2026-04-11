import type { UiNode } from "../schema/index.js";
import { findByGeometry, parseGeometryQuery } from "./geometry.js";

/**
 * A query match with confidence scoring.
 */
export interface QueryMatch {
  node: UiNode;
  score: number;
  matchedBy: string;
}

/**
 * Parsed query components extracted from a natural-language-style selector string.
 */
interface ParsedQuery {
  role: string | null;
  name: string | null;
  text: string | null;
  id: string | null;
  clickableOnly: boolean;
  visibleOnly: boolean;
  labeledAs: string | null;
}

/**
 * Query resolution order (highest to lowest priority):
 * 1. exact id
 * 2. explicit role + name match
 * 3. exact text match
 * 4. accessible name match
 * 5. fuzzy text match
 * 6. geometry fallback (e.g. "nearest button to n_5", "button below n_3")
 */
export function queryNodes(
  nodes: readonly UiNode[],
  query: string,
): QueryMatch[] {
  // Check if this is a geometry query first
  const geoQuery = parseGeometryQuery(query);
  if (geoQuery !== null) {
    return resolveGeometryQuery(nodes, geoQuery);
  }

  const parsed = parseQuery(query);
  const matches: QueryMatch[] = [];

  for (const node of nodes) {
    const match = scoreNode(node, parsed);
    if (match !== null) {
      matches.push(match);
    }
  }

  // Sort by score descending, then by node id for stability
  matches.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    return a.node.id.localeCompare(b.node.id);
  });

  return matches;
}

/**
 * Resolve a geometry query into scored matches.
 */
function resolveGeometryQuery(
  nodes: readonly UiNode[],
  geoQuery: ReturnType<typeof parseGeometryQuery> & object,
): QueryMatch[] {
  const roleFilter = (n: UiNode): boolean => {
    const aliases = ROLE_ALIASES[geoQuery.role];
    if (aliases !== undefined) {
      return (
        aliases.includes(n.role.toLowerCase()) ||
        aliases.includes(n.type.toLowerCase())
      );
    }
    return (
      n.role.toLowerCase() === geoQuery.role ||
      n.type.toLowerCase() === geoQuery.role
    );
  };

  const geoMatches = findByGeometry(
    nodes,
    geoQuery.referenceId,
    geoQuery.relation,
    roleFilter,
  );

  // Convert to QueryMatch with distance-based scoring
  const maxDist = geoMatches.length > 0
    ? Math.max(...geoMatches.map((m) => m.distance), 1)
    : 1;

  return geoMatches.map((m) => ({
    node: m.node,
    score: Math.max(0.5, 1.0 - m.distance / maxDist * 0.5),
    matchedBy: `geometry:${m.relation}`,
  }));
}

/**
 * Find the single best match, or null if no confident match exists.
 */
export function queryBestMatch(
  nodes: readonly UiNode[],
  query: string,
): QueryMatch | null {
  const matches = queryNodes(nodes, query);
  return matches[0] ?? null;
}

/**
 * Find a node by exact ID.
 */
export function findNodeById(
  nodes: readonly UiNode[],
  id: string,
): UiNode | undefined {
  return nodes.find((n) => n.id === id);
}

/**
 * Parse a natural-language-style query string into structured components.
 *
 * Supported patterns:
 * - "n_14" -> exact id match
 * - "button named sign in" -> role=button, name="sign in"
 * - "field labeled email" -> role=textbox, labeledAs="email"
 * - "clickable text contains continue" -> clickableOnly, text contains "continue"
 * - "first visible button" -> role=button, visibleOnly
 * - "button text login" -> role=button, text="login"
 */
export function parseQuery(query: string): ParsedQuery {
  const trimmed = query.trim().toLowerCase();

  // Exact node ID: supports sequential (n_1) and stable hashed (n_deadbeef_0) formats
  if (/^n_[a-f0-9]+(?:_\d+)?$/.test(trimmed)) {
    return {
      role: null,
      name: null,
      text: null,
      id: trimmed,
      clickableOnly: false,
      visibleOnly: false,
      labeledAs: null,
    };
  }

  const result: ParsedQuery = {
    role: null,
    name: null,
    text: null,
    id: null,
    clickableOnly: false,
    visibleOnly: false,
    labeledAs: null,
  };

  let remaining = trimmed;

  // Extract modifiers
  if (remaining.includes("clickable")) {
    result.clickableOnly = true;
    remaining = remaining.replace("clickable", "").trim();
  }
  if (remaining.includes("visible")) {
    result.visibleOnly = true;
    remaining = remaining.replace("visible", "").trim();
  }
  if (remaining.startsWith("first ")) {
    remaining = remaining.slice(6).trim();
  }

  // Check "text contains" pattern before role extraction,
  // since "text" is both a role alias and a keyword in "text contains <value>".
  const textContainsMatch = /\btext\s+contains\s+(.+)/i.exec(remaining);
  if (textContainsMatch?.[1] !== undefined) {
    result.text = textContainsMatch[1].trim();
    return result;
  }

  // Extract role
  const roleMatch = extractRole(remaining);
  if (roleMatch !== null) {
    result.role = roleMatch.role;
    remaining = roleMatch.rest;
  }

  // Extract "named <value>"
  const namedMatch = /\bnamed\s+(.+)/i.exec(remaining);
  if (namedMatch?.[1] !== undefined) {
    result.name = namedMatch[1].trim();
    return result;
  }

  // Extract "labeled <value>" or "labelled <value>"
  const labeledMatch = /\blabell?ed\s+(.+)/i.exec(remaining);
  if (labeledMatch?.[1] !== undefined) {
    result.labeledAs = labeledMatch[1].trim();
    return result;
  }

  // Extract "text <value>" (after role extraction to avoid ambiguity with "text" role)
  const textMatch = /\btext\s+(.+)/i.exec(remaining);
  if (textMatch?.[1] !== undefined) {
    result.text = textMatch[1].trim();
    return result;
  }

  // Whatever is left is treated as a text/name search
  if (remaining.trim() !== "") {
    result.text = remaining.trim();
  }

  return result;
}

/**
 * Score a node against parsed query components.
 * Returns null if the node doesn't match at all.
 */
function scoreNode(node: UiNode, query: ParsedQuery): QueryMatch | null {
  // Filter: visibility and clickability
  if (query.visibleOnly && !node.visible) return null;
  if (query.clickableOnly && !node.clickable) return null;

  // Exact ID match — highest priority
  if (query.id !== null) {
    if (node.id === query.id) {
      return { node, score: 1.0, matchedBy: "exact_id" };
    }
    return null;
  }

  let bestScore = 0;
  let bestMatchedBy = "";

  // Role match
  const roleMatches =
    query.role === null || matchesRole(node, query.role);
  if (!roleMatches) return null;

  // Boost for role match
  if (query.role !== null) {
    bestScore = 0.3;
    bestMatchedBy = "role";
  }

  // Accessible name exact match
  if (query.name !== null) {
    const nameScore = matchName(node, query.name);
    if (nameScore > 0) {
      const total = bestScore + nameScore * 0.7;
      if (total > bestScore) {
        bestScore = total;
        bestMatchedBy = "role_and_name";
      }
    } else {
      return null;
    }
  }

  // Label match
  if (query.labeledAs !== null) {
    const labelScore = matchLabel(node, query.labeledAs);
    if (labelScore > 0) {
      const total = bestScore + labelScore * 0.7;
      if (total > bestScore) {
        bestScore = total;
        bestMatchedBy = "labeled";
      }
    } else {
      return null;
    }
  }

  // Text match
  if (query.text !== null) {
    const textScore = matchText(node, query.text);
    if (textScore > 0) {
      const total = Math.max(bestScore, textScore);
      if (total >= bestScore) {
        bestScore = total;
        bestMatchedBy =
          textScore >= 0.9 ? "exact_text" : "fuzzy_text";
      }
    } else if (query.name === null && query.labeledAs === null) {
      // Text was the only search criterion and it didn't match
      return null;
    }
  }

  if (bestScore <= 0) return null;

  return {
    node,
    score: Math.min(bestScore, 1.0),
    matchedBy: bestMatchedBy,
  };
}

/** Role aliases — maps common query terms to matching UI node roles/types. */
const ROLE_ALIASES: Record<string, string[]> = {
  button: ["button", "link_button", "submit"],
  field: ["textbox", "input", "textarea", "edittext", "searchbox", "combobox"],
  textbox: ["textbox", "input", "textarea", "edittext", "searchbox"],
  input: ["textbox", "input", "textarea", "edittext", "searchbox"],
  link: ["link", "a"],
  image: ["image", "img"],
  checkbox: ["checkbox"],
  radio: ["radio"],
  heading: ["heading", "h1", "h2", "h3", "h4", "h5", "h6"],
  text: ["text", "statictext", "label", "paragraph"],
  select: ["combobox", "listbox", "select"],
  tab: ["tab"],
  list: ["list"],
  listitem: ["listitem"],
  dialog: ["dialog", "alertdialog"],
  navigation: ["navigation", "nav"],
};

function matchesRole(node: UiNode, queryRole: string): boolean {
  const normalizedNodeRole = node.role.toLowerCase();
  const normalizedNodeType = node.type.toLowerCase();
  const aliases = ROLE_ALIASES[queryRole];

  if (aliases !== undefined) {
    return (
      aliases.includes(normalizedNodeRole) ||
      aliases.includes(normalizedNodeType)
    );
  }

  return normalizedNodeRole === queryRole || normalizedNodeType === queryRole;
}

function matchName(node: UiNode, queryName: string): number {
  const name = (node.name ?? "").toLowerCase();
  const text = node.text.toLowerCase();

  // Exact match on accessible name
  if (name === queryName) return 1.0;
  // Exact match on visible text
  if (text === queryName) return 0.95;
  // Contains match on name
  if (name.includes(queryName)) return 0.8;
  // Contains match on text
  if (text.includes(queryName)) return 0.75;
  return 0;
}

function matchLabel(node: UiNode, label: string): number {
  const name = (node.name ?? "").toLowerCase();
  const placeholder = (node.placeholder ?? "").toLowerCase();
  const description = (node.description ?? "").toLowerCase();

  if (name === label) return 1.0;
  if (placeholder === label) return 0.9;
  if (description === label) return 0.85;
  if (name.includes(label)) return 0.7;
  if (placeholder.includes(label)) return 0.65;
  return 0;
}

function matchText(node: UiNode, queryText: string): number {
  const text = node.text.toLowerCase();
  const name = (node.name ?? "").toLowerCase();

  // Exact text match
  if (text === queryText) return 0.95;
  // Exact name match
  if (name === queryText) return 0.9;
  // Text contains
  if (text.includes(queryText)) return 0.7;
  // Name contains
  if (name.includes(queryText)) return 0.65;
  // Fuzzy: query words all appear in text
  const queryWords = queryText.split(/\s+/);
  const allWordsMatch = queryWords.every(
    (w) => text.includes(w) || name.includes(w),
  );
  if (allWordsMatch && queryWords.length > 1) return 0.5;

  return 0;
}

interface RoleExtraction {
  role: string;
  rest: string;
}

function extractRole(input: string): RoleExtraction | null {
  const knownRoles = Object.keys(ROLE_ALIASES);
  for (const role of knownRoles) {
    if (input.startsWith(role + " ") || input === role) {
      return {
        role,
        rest: input.slice(role.length).trim(),
      };
    }
  }
  return null;
}
