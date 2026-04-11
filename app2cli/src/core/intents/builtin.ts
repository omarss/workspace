import type { UiNode } from "../schema/index.js";
import { findMatching, isButtonNode, isInputNode, textMatches } from "../patterns/types.js";
import type { Intent, IntentMatch } from "./types.js";

/**
 * "login" — find and click the primary login/sign-in action.
 */
export class LoginIntent implements Intent {
  readonly name = "login";
  readonly description = "Click the primary sign-in / login button";

  resolve(nodes: readonly UiNode[]): IntentMatch | null {
    const patterns = ["sign in", "log in", "login", "signin"];
    const candidates = findMatching(
      nodes,
      (n) => isButtonNode(n) && n.visible && n.enabled && textMatches(n, patterns),
    );

    if (candidates.length === 0) return null;

    // Prefer exact text match, then name match
    const best = pickBest(candidates, patterns);
    return {
      intentName: this.name,
      node: best,
      score: 0.95,
      action: "click",
      suggestedInput: null,
      reason: `button with text "${best.text.length > 0 ? best.text : (best.name ?? "")}" matches login intent`,
    };
  }
}

/**
 * "signup" — find and click the sign-up / register action.
 */
export class SignupIntent implements Intent {
  readonly name = "signup";
  readonly description = "Click the sign-up / register button";

  resolve(nodes: readonly UiNode[]): IntentMatch | null {
    const patterns = ["sign up", "signup", "register", "create account", "get started", "join"];
    const candidates = findMatching(
      nodes,
      (n) => isButtonNode(n) && n.visible && n.enabled && textMatches(n, patterns),
    );

    if (candidates.length === 0) return null;
    const best = pickBest(candidates, patterns);
    return {
      intentName: this.name,
      node: best,
      score: 0.95,
      action: "click",
      suggestedInput: null,
      reason: `button matches signup intent`,
    };
  }
}

/**
 * "continue" — find and click the primary continue/next action.
 */
export class ContinueIntent implements Intent {
  readonly name = "continue";
  readonly description = "Click the continue / next button";

  resolve(nodes: readonly UiNode[]): IntentMatch | null {
    const patterns = ["continue", "next", "proceed", "go", "done", "ok"];
    const candidates = findMatching(
      nodes,
      (n) => isButtonNode(n) && n.visible && n.enabled && textMatches(n, patterns),
    );

    if (candidates.length === 0) return null;
    const best = pickBest(candidates, patterns);
    return {
      intentName: this.name,
      node: best,
      score: 0.93,
      action: "click",
      suggestedInput: null,
      reason: `button matches continue intent`,
    };
  }
}

/**
 * "submit" — find and click the primary submit action.
 */
export class SubmitIntent implements Intent {
  readonly name = "submit";
  readonly description = "Click the submit / send / save button";

  resolve(nodes: readonly UiNode[]): IntentMatch | null {
    const patterns = ["submit", "send", "save", "confirm", "apply", "pay", "place order"];
    const candidates = findMatching(
      nodes,
      (n) => isButtonNode(n) && n.visible && n.enabled && textMatches(n, patterns),
    );

    if (candidates.length === 0) return null;
    const best = pickBest(candidates, patterns);
    return {
      intentName: this.name,
      node: best,
      score: 0.93,
      action: "click",
      suggestedInput: null,
      reason: `button matches submit intent`,
    };
  }
}

/**
 * "dismiss" — close a dialog, banner, or popup.
 */
export class DismissIntent implements Intent {
  readonly name = "dismiss";
  readonly description = "Dismiss / close the current dialog or overlay";

  resolve(nodes: readonly UiNode[]): IntentMatch | null {
    const patterns = ["close", "dismiss", "cancel", "no thanks", "got it", "maybe later", "skip"];
    const candidates = findMatching(
      nodes,
      (n) => n.clickable && n.visible && textMatches(n, patterns),
    );

    if (candidates.length === 0) return null;
    const best = pickBest(candidates, patterns);
    return {
      intentName: this.name,
      node: best,
      score: 0.90,
      action: "click",
      suggestedInput: null,
      reason: `element matches dismiss intent`,
    };
  }
}

/**
 * "back" — navigate back.
 */
export class BackIntent implements Intent {
  readonly name = "back";
  readonly description = "Go back to the previous screen";

  resolve(nodes: readonly UiNode[]): IntentMatch | null {
    const patterns = ["back", "go back", "return", "previous"];
    const candidates = findMatching(
      nodes,
      (n) => n.clickable && n.visible && textMatches(n, patterns),
    );

    if (candidates.length === 0) return null;
    const best = pickBest(candidates, patterns);
    return {
      intentName: this.name,
      node: best,
      score: 0.88,
      action: "click",
      suggestedInput: null,
      reason: `element matches back intent`,
    };
  }
}

/**
 * "search" — focus the search input.
 */
export class SearchIntent implements Intent {
  readonly name = "search";
  readonly description = "Focus the search input field";

  resolve(nodes: readonly UiNode[]): IntentMatch | null {
    const searchInputs = findMatching(
      nodes,
      (n) =>
        n.visible &&
        (isInputNode(n) || n.role === "searchbox") &&
        textMatches(n, ["search", "find", "look up"]),
    );

    if (searchInputs.length === 0) return null;
    const best = searchInputs[0];
    if (best === undefined) return null;

    return {
      intentName: this.name,
      node: best,
      score: 0.92,
      action: "click",
      suggestedInput: null,
      reason: `search input found`,
    };
  }
}

// ---- Helpers ----

/**
 * Pick the best candidate by preferring exact text matches over partial matches.
 */
function pickBest(candidates: UiNode[], patterns: string[]): UiNode {
  // Prefer exact text match
  for (const pattern of patterns) {
    const exact = candidates.find(
      (n) => n.text.toLowerCase() === pattern || (n.name ?? "").toLowerCase() === pattern,
    );
    if (exact !== undefined) return exact;
  }

  // Prefer contains match on text over name
  for (const pattern of patterns) {
    const contains = candidates.find((n) => n.text.toLowerCase().includes(pattern));
    if (contains !== undefined) return contains;
  }

  // Fall back to first candidate
  return candidates[0] ?? candidates[0]!; // eslint-disable-line @typescript-eslint/no-non-null-assertion -- candidates.length > 0 guaranteed by callers
}
