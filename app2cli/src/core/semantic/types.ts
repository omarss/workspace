/**
 * Semantic object kinds — higher-level groupings above raw UI nodes.
 */
export type SemanticObjectKind =
  | "form"
  | "form_field"
  | "action_primary"
  | "action_secondary"
  | "navigation_region"
  | "dialog"
  | "menu"
  | "tab_group"
  | "list_view"
  | "search_surface"
  | "auth_flow"
  | "error_message"
  | "success_message"
  | "warning_message";

/**
 * A semantic object — a meaningful grouping of UI nodes.
 */
export interface SemanticObject {
  /** Unique semantic object ID */
  id: string;
  /** The kind of semantic object */
  kind: SemanticObjectKind;
  /** Human-readable label for this object */
  label: string;
  /** IDs of the UI nodes that compose this object */
  nodeIds: string[];
  /** Additional structured properties */
  properties: Record<string, unknown>;
}

/**
 * A form field with its associated label and validation state.
 */
export interface FormFieldInfo {
  /** Node ID of the input element */
  inputNodeId: string;
  /** Label text (from aria-label, associated label, or placeholder) */
  label: string;
  /** Whether the field is required */
  required: boolean;
  /** Field type: text, email, password, number, etc. */
  fieldType: string;
  /** Current value */
  value: string | null;
  /** Validation error message (if any) */
  validationError: string | null;
}

/**
 * A complete form with fields and actions.
 */
export interface FormInfo {
  /** Semantic object ID */
  id: string;
  /** Form label or heading */
  label: string;
  /** Fields in the form */
  fields: FormFieldInfo[];
  /** Primary action (submit button) node ID */
  primaryAction: string | null;
  /** Secondary action node IDs (cancel, reset, etc.) */
  secondaryActions: string[];
}
