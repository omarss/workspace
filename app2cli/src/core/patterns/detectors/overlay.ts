import type { UiNode } from "../../schema/index.js";
import { buildMatch, findMatching, textMatches } from "../types.js";
import type { PatternDetector } from "../types.js";

/**
 * Detects modal dialogs.
 *
 * Evidence:
 * - dialog or alertdialog role
 * - isolated visual container
 * - close/cancel/dismiss affordance
 */
export class ModalDialogDetector implements PatternDetector {
  readonly kind = "modal_dialog" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const dialogs = findMatching(
      nodes,
      (n) =>
        n.role === "dialog" ||
        n.role === "alertdialog" ||
        n.type === "dialog",
    );

    if (dialogs.length === 0) return null;

    const firstDialog = dialogs[0];
    if (firstDialog === undefined) return null;

    const dismissPatterns = [
      "close",
      "cancel",
      "dismiss",
      "ok",
      "got it",
      "no thanks",
    ];
    const dismissActions = findMatching(nodes, (n) =>
      n.clickable && textMatches(n, dismissPatterns),
    );

    let confidence = 0.8;
    if (dismissActions.length > 0) confidence += 0.1;
    if (firstDialog.visible) confidence += 0.05;

    return buildMatch(
      this.kind,
      Math.min(confidence, 1.0),
      {
        items: [firstDialog.id],
        actions: dismissActions.map((n) => n.id),
        texts: dismissActions.map((n) => n.text).filter((t) => t.length > 0),
      },
      1,
    );
  }
}

/**
 * Detects bottom sheets.
 */
export class BottomSheetDetector implements PatternDetector {
  readonly kind = "bottom_sheet" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const screenHeight = getMaxY(nodes);
    const sheetThreshold = screenHeight * 0.5;

    // Look for a container in the lower half that overlays content
    const candidates = findMatching(
      nodes,
      (n) =>
        n.bounds !== null &&
        n.bounds.y >= sheetThreshold &&
        n.bounds.height > screenHeight * 0.2 &&
        n.visible &&
        n.type === "container",
    );

    if (candidates.length === 0) return null;

    // Check for typical bottom sheet indicators
    for (const candidate of candidates) {
      const children = nodes.filter((n) =>
        candidate.children.includes(n.id),
      );
      const hasClickableContent = children.some((c) => c.clickable);

      if (hasClickableContent && children.length >= 2) {
        return buildMatch(
          this.kind,
          0.75,
          {
            items: [candidate.id],
            actions: children
              .filter((c) => c.clickable)
              .map((c) => c.id),
          },
          1,
        );
      }
    }

    return null;
  }
}

/**
 * Detects toast/snackbar messages.
 */
export class ToastDetector implements PatternDetector {
  readonly kind = "toast" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const toastPatterns = [
      "toast",
      "snackbar",
      "notification",
    ];

    // Look for role-based toasts
    const roleToasts = findMatching(
      nodes,
      (n) =>
        n.role === "alert" ||
        n.role === "status" ||
        textMatches(n, toastPatterns),
    );

    if (roleToasts.length > 0) {
      const first = roleToasts[0];
      if (first !== undefined) {
        return buildMatch(
          this.kind,
          0.8,
          {
            items: [first.id],
            texts: roleToasts
              .map((n) => n.text)
              .filter((t) => t.length > 0),
          },
          1,
        );
      }
    }

    return null;
  }
}

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
