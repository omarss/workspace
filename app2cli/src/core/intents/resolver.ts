import type { UiNode } from "../schema/index.js";
import {
  BackIntent,
  ContinueIntent,
  DismissIntent,
  LoginIntent,
  SearchIntent,
  SignupIntent,
  SubmitIntent,
} from "./builtin.js";
import type { Intent, IntentMatch } from "./types.js";

/**
 * All built-in intents, registered in priority order.
 */
function createDefaultIntents(): Intent[] {
  return [
    new LoginIntent(),
    new SignupIntent(),
    new SubmitIntent(),
    new ContinueIntent(),
    new DismissIntent(),
    new BackIntent(),
    new SearchIntent(),
  ];
}

/**
 * Resolve an intent by name against the current UI state.
 * Returns the best match, or null if the intent doesn't apply.
 */
export function resolveIntent(
  intentName: string,
  nodes: readonly UiNode[],
  intents?: Intent[],
): IntentMatch | null {
  const registry = intents ?? createDefaultIntents();
  const intent = registry.find((i) => i.name === intentName);

  if (intent === undefined) return null;
  return intent.resolve(nodes);
}

/**
 * List all registered intent names.
 */
export function listIntentNames(intents?: Intent[]): string[] {
  const registry = intents ?? createDefaultIntents();
  return registry.map((i) => i.name);
}

/**
 * Try to resolve a string as an intent first, then fall back to a query.
 * This is the unified resolution path used by CLI commands.
 */
export function tryResolveAsIntent(
  input: string,
  nodes: readonly UiNode[],
): IntentMatch | null {
  const normalized = input.trim().toLowerCase();
  return resolveIntent(normalized, nodes);
}
