import { z } from "zod/v4";

/**
 * All recognized UI pattern kinds.
 * Each maps to a deterministic detector in the pattern engine.
 */
export const PatternKindSchema = z.enum([
  "login_form",
  "signup_form",
  "otp_screen",
  "modal_dialog",
  "bottom_sheet",
  "toast",
  "top_navigation",
  "bottom_navigation",
  "tabs",
  "search_surface",
  "settings_page",
  "dashboard_cards",
  "list_with_actions",
  "empty_state",
  "error_state",
  "checkout_form",
  "payment_picker",
]);

export type PatternKind = z.infer<typeof PatternKindSchema>;

/**
 * Evidence that supports a pattern detection.
 */
export const PatternEvidenceSchema = z.object({
  /** Node IDs of relevant fields */
  fields: z.array(z.string()).optional(),

  /** Node IDs of relevant actions/buttons */
  actions: z.array(z.string()).optional(),

  /** Node IDs of relevant items (nav items, list items, etc.) */
  items: z.array(z.string()).optional(),

  /** Relevant text strings found */
  texts: z.array(z.string()).optional(),
});

export type PatternEvidence = z.infer<typeof PatternEvidenceSchema>;

/**
 * A recognized UI pattern with confidence scoring.
 */
export const PatternMatchSchema = z.object({
  /** Pattern match identifier, e.g. "pat_login_1" */
  id: z.string(),

  /** The kind of pattern recognized */
  kind: PatternKindSchema,

  /** Confidence score: 0.0 to 1.0 */
  confidence: z.number().min(0).max(1),

  /** Evidence supporting the detection */
  evidence: PatternEvidenceSchema,

  /** IDs of semantic objects this pattern maps to */
  semanticObjectIds: z.array(z.string()).optional(),
});

export type PatternMatch = z.infer<typeof PatternMatchSchema>;
