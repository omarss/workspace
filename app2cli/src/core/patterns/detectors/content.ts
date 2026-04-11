import type { UiNode } from "../../schema/index.js";
import { buildMatch, findMatching, isInputNode, textMatches } from "../types.js";
import type { PatternDetector } from "../types.js";

/**
 * Detects search surfaces (search bars, search forms).
 */
export class SearchSurfaceDetector implements PatternDetector {
  readonly kind = "search_surface" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const searchInputs = findMatching(
      nodes,
      (n) =>
        (isInputNode(n) || n.role === "searchbox") &&
        textMatches(n, ["search", "find", "look up"]),
    );

    if (searchInputs.length === 0) return null;

    const searchButtons = findMatching(
      nodes,
      (n) => n.clickable && textMatches(n, ["search", "find", "go"]),
    );

    let confidence = 0.75;
    if (searchButtons.length > 0) confidence += 0.1;

    return buildMatch(
      this.kind,
      Math.min(confidence, 1.0),
      {
        fields: searchInputs.map((n) => n.id),
        actions: searchButtons.map((n) => n.id),
      },
      1,
    );
  }
}

/**
 * Detects empty state screens.
 */
export class EmptyStateDetector implements PatternDetector {
  readonly kind = "empty_state" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const emptyPatterns = [
      "no results",
      "nothing here",
      "no items",
      "empty",
      "no data",
      "get started",
      "nothing to show",
      "no content",
    ];

    const emptyNodes = findMatching(nodes, (n) =>
      textMatches(n, emptyPatterns) && n.visible,
    );

    if (emptyNodes.length === 0) return null;

    // If there are very few visible interactable nodes, it's more likely empty state
    const visibleInteractable = findMatching(
      nodes,
      (n) => n.visible && n.clickable,
    );

    let confidence = 0.7;
    if (visibleInteractable.length < 5) confidence += 0.1;
    if (emptyNodes.length >= 2) confidence += 0.05;

    return buildMatch(
      this.kind,
      Math.min(confidence, 1.0),
      {
        items: emptyNodes.map((n) => n.id),
        texts: emptyNodes.map((n) => n.text).filter((t) => t.length > 0),
      },
      1,
    );
  }
}

/**
 * Detects error state screens.
 */
export class ErrorStateDetector implements PatternDetector {
  readonly kind = "error_state" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const errorPatterns = [
      "error",
      "failed",
      "something went wrong",
      "try again",
      "could not",
      "unable to",
      "oops",
      "problem",
      "not found",
      "404",
      "500",
    ];

    const errorNodes = findMatching(nodes, (n) =>
      textMatches(n, errorPatterns) && n.visible,
    );

    if (errorNodes.length === 0) return null;

    const retryButtons = findMatching(
      nodes,
      (n) => n.clickable && textMatches(n, ["try again", "retry", "reload"]),
    );

    let confidence = 0.7;
    if (retryButtons.length > 0) confidence += 0.15;
    if (errorNodes.length >= 2) confidence += 0.05;

    return buildMatch(
      this.kind,
      Math.min(confidence, 1.0),
      {
        items: errorNodes.map((n) => n.id),
        actions: retryButtons.map((n) => n.id),
        texts: errorNodes.map((n) => n.text).filter((t) => t.length > 0),
      },
      1,
    );
  }
}

/**
 * Detects list views with per-item actions.
 */
export class ListWithActionsDetector implements PatternDetector {
  readonly kind = "list_with_actions" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const listNodes = findMatching(
      nodes,
      (n) => n.type === "list" || n.role === "list",
    );

    if (listNodes.length === 0) return null;

    for (const list of listNodes) {
      const listItems = nodes.filter(
        (n) => list.children.includes(n.id) && n.clickable,
      );

      if (listItems.length >= 3) {
        return buildMatch(
          this.kind,
          0.8,
          {
            items: listItems.map((n) => n.id),
          },
          1,
        );
      }
    }

    return null;
  }
}

/**
 * Detects settings pages.
 */
export class SettingsPageDetector implements PatternDetector {
  readonly kind = "settings_page" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const settingsPatterns = [
      "settings",
      "preferences",
      "configuration",
      "options",
    ];

    const settingsHeaders = findMatching(nodes, (n) =>
      textMatches(n, settingsPatterns) &&
      (n.role === "heading" || n.type === "heading" || n.type === "text"),
    );

    if (settingsHeaders.length === 0) return null;

    // Settings pages typically have many clickable list items
    const clickableItems = findMatching(
      nodes,
      (n) => n.clickable && n.visible,
    );

    let confidence = 0.65;
    if (clickableItems.length >= 5) confidence += 0.15;
    if (settingsHeaders.length > 0) confidence += 0.1;

    return buildMatch(
      this.kind,
      Math.min(confidence, 1.0),
      {
        items: settingsHeaders.map((n) => n.id),
        texts: settingsHeaders.map((n) => n.text).filter((t) => t.length > 0),
      },
      1,
    );
  }
}

/**
 * Detects dashboard-style card grids.
 */
export class DashboardCardsDetector implements PatternDetector {
  readonly kind = "dashboard_cards" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    // Look for groups of similarly-sized, visually-arranged containers
    const cardCandidates = findMatching(
      nodes,
      (n) =>
        n.visible &&
        n.bounds !== null &&
        n.type === "container" &&
        n.children.length >= 2,
    );

    // Group by similar size
    const sizeGroups = groupBySimilarSize(cardCandidates);
    const largestGroup = sizeGroups.reduce<UiNode[]>(
      (best, group) => (group.length > best.length ? group : best),
      [],
    );

    if (largestGroup.length < 3) return null;

    return buildMatch(
      this.kind,
      0.7,
      { items: largestGroup.map((n) => n.id) },
      1,
    );
  }
}

function groupBySimilarSize(nodes: UiNode[]): UiNode[][] {
  const groups: UiNode[][] = [];
  const tolerance = 50;

  for (const node of nodes) {
    if (node.bounds === null) continue;

    let placed = false;
    for (const group of groups) {
      const ref = group[0];
      if (
        ref !== undefined &&
        ref.bounds !== null &&
        Math.abs(ref.bounds.width - node.bounds.width) < tolerance &&
        Math.abs(ref.bounds.height - node.bounds.height) < tolerance
      ) {
        group.push(node);
        placed = true;
        break;
      }
    }

    if (!placed) {
      groups.push([node]);
    }
  }

  return groups;
}
