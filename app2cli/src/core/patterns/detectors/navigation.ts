import type { UiNode } from "../../schema/index.js";
import { buildMatch, findMatching, isButtonNode } from "../types.js";
import type { PatternDetector } from "../types.js";

/**
 * Detects bottom navigation bars.
 *
 * Evidence:
 * - Persistent region near bottom edge
 * - 3-5 peer clickable items
 * - One selected state
 */
export class BottomNavigationDetector implements PatternDetector {
  readonly kind = "bottom_navigation" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    // Look for navigation-type containers near the bottom
    const navContainers = findMatching(
      nodes,
      (n) =>
        n.type === "navigation" ||
        n.role === "navigation" ||
        n.role === "tablist",
    );

    // Also look for clusters of clickable items near the bottom of the screen
    const screenHeight = getMaxY(nodes);
    const bottomThreshold = screenHeight * 0.85;

    for (const nav of navContainers) {
      if (nav.bounds !== null && nav.bounds.y >= bottomThreshold) {
        const childNodes = resolveChildren(nav, nodes);
        const clickableChildren = childNodes.filter((c) => c.clickable);

        if (clickableChildren.length >= 3 && clickableChildren.length <= 6) {
          const hasSelected = clickableChildren.some((c) => c.selected);
          let confidence = 0.7;
          if (hasSelected) confidence += 0.15;
          if (clickableChildren.length >= 3 && clickableChildren.length <= 5) {
            confidence += 0.1;
          }

          return buildMatch(
            this.kind,
            Math.min(confidence, 1.0),
            { items: clickableChildren.map((c) => c.id) },
            1,
          );
        }
      }
    }

    // Fallback: cluster of clickable items at bottom without explicit nav container
    const bottomItems = findMatching(
      nodes,
      (n) =>
        n.clickable &&
        n.bounds !== null &&
        n.bounds.y >= bottomThreshold &&
        (isButtonNode(n) || n.role === "tab"),
    );

    if (bottomItems.length >= 3 && bottomItems.length <= 6) {
      return buildMatch(
        this.kind,
        0.75,
        { items: bottomItems.map((n) => n.id) },
        1,
      );
    }

    return null;
  }
}

/**
 * Detects top navigation bars / toolbars.
 */
export class TopNavigationDetector implements PatternDetector {
  readonly kind = "top_navigation" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const topThreshold = 0.15;
    const screenHeight = getMaxY(nodes);

    const navNodes = findMatching(
      nodes,
      (n) =>
        (n.type === "navigation" ||
          n.role === "navigation" ||
          n.role === "toolbar" ||
          n.role === "banner") &&
        n.bounds !== null &&
        n.bounds.y < screenHeight * topThreshold,
    );

    if (navNodes.length === 0) return null;

    const firstNav = navNodes[0];
    if (firstNav === undefined) return null;

    const childNodes = resolveChildren(firstNav, nodes);
    const clickableChildren = childNodes.filter((c) => c.clickable);

    let confidence = 0.7;
    if (clickableChildren.length >= 2) confidence += 0.1;
    if (firstNav.bounds !== null && firstNav.bounds.y < screenHeight * 0.1) {
      confidence += 0.1;
    }

    return buildMatch(
      this.kind,
      Math.min(confidence, 1.0),
      {
        items: [firstNav.id, ...clickableChildren.map((c) => c.id)],
      },
      1,
    );
  }
}

/**
 * Detects tab bars.
 */
export class TabsDetector implements PatternDetector {
  readonly kind = "tabs" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const tabLists = findMatching(
      nodes,
      (n) => n.role === "tablist" || n.type === "tabs",
    );

    if (tabLists.length === 0) return null;

    const firstTabList = tabLists[0];
    if (firstTabList === undefined) return null;

    const tabs = resolveChildren(firstTabList, nodes).filter(
      (c) => c.role === "tab" || c.clickable,
    );

    if (tabs.length < 2) return null;

    const hasSelected = tabs.some((t) => t.selected);
    let confidence = 0.7;
    if (hasSelected) confidence += 0.15;
    if (tabs.length >= 2 && tabs.length <= 8) confidence += 0.1;

    return buildMatch(
      this.kind,
      Math.min(confidence, 1.0),
      { items: tabs.map((t) => t.id) },
      1,
    );
  }
}

// ---- Helpers ----

function getMaxY(nodes: readonly UiNode[]): number {
  let maxY = 0;
  for (const node of nodes) {
    if (node.bounds !== null) {
      const bottom = node.bounds.y + node.bounds.height;
      if (bottom > maxY) maxY = bottom;
    }
  }
  return maxY > 0 ? maxY : 1920;
}

function resolveChildren(
  parent: UiNode,
  allNodes: readonly UiNode[],
): UiNode[] {
  const childSet = new Set(parent.children);
  return allNodes.filter((n) => childSet.has(n.id));
}
