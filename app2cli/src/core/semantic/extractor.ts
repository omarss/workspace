import type { UiNode } from "../schema/index.js";
import type { FormFieldInfo, FormInfo, SemanticObject } from "./types.js";

/**
 * Extract semantic objects from a flat array of UI nodes.
 *
 * This layer sits above raw nodes and pattern detection.
 * It identifies meaningful groupings: forms with fields, labeled actions,
 * navigation regions, etc.
 */
export function extractSemanticObjects(
  nodes: readonly UiNode[],
): SemanticObject[] {
  const objects: SemanticObject[] = [];
  let counter = 0;

  const nextId = (): string => {
    counter++;
    return `obj_${String(counter)}`;
  };

  // Extract forms
  for (const form of extractForms(nodes)) {
    objects.push({
      id: nextId(),
      kind: "form",
      label: form.label,
      nodeIds: [
        ...form.fields.map((f) => f.inputNodeId),
        ...(form.primaryAction !== null ? [form.primaryAction] : []),
        ...form.secondaryActions,
      ],
      properties: { form },
    });
  }

  // Extract primary and secondary actions
  for (const node of nodes) {
    if (!node.clickable || !node.visible) continue;

    if (isPrimaryAction(node)) {
      objects.push({
        id: nextId(),
        kind: "action_primary",
        label: node.text.length > 0 ? node.text : (node.name ?? "action"),
        nodeIds: [node.id],
        properties: {},
      });
    } else if (isSecondaryAction(node)) {
      objects.push({
        id: nextId(),
        kind: "action_secondary",
        label: node.text.length > 0 ? node.text : (node.name ?? "action"),
        nodeIds: [node.id],
        properties: {},
      });
    }
  }

  // Extract navigation regions
  for (const node of nodes) {
    if (node.role === "navigation" || node.type === "navigation") {
      objects.push({
        id: nextId(),
        kind: "navigation_region",
        label: node.name ?? "navigation",
        nodeIds: [node.id, ...node.children],
        properties: {},
      });
    }
  }

  // Extract dialogs
  for (const node of nodes) {
    if (node.role === "dialog" || node.role === "alertdialog") {
      objects.push({
        id: nextId(),
        kind: "dialog",
        label: node.name ?? node.text,
        nodeIds: [node.id, ...node.children],
        properties: {},
      });
    }
  }

  // Extract error/success/warning messages
  for (const node of nodes) {
    if (!node.visible || node.text.length === 0) continue;

    const textLower = node.text.toLowerCase();
    if (
      node.role === "alert" ||
      textLower.includes("error") ||
      textLower.includes("failed") ||
      textLower.includes("something went wrong")
    ) {
      objects.push({
        id: nextId(),
        kind: "error_message",
        label: node.text,
        nodeIds: [node.id],
        properties: {},
      });
    } else if (
      textLower.includes("success") ||
      textLower.includes("completed") ||
      textLower.includes("confirmed")
    ) {
      objects.push({
        id: nextId(),
        kind: "success_message",
        label: node.text,
        nodeIds: [node.id],
        properties: {},
      });
    }
  }

  return objects;
}

/**
 * Extract form structures from the node tree.
 */
export function extractForms(nodes: readonly UiNode[]): FormInfo[] {
  const forms: FormInfo[] = [];
  let formCounter = 0;

  // Find explicit form containers
  const formNodes = nodes.filter(
    (n) => n.type === "form" || n.role === "form",
  );

  for (const formNode of formNodes) {
    const allDescendants = collectDescendants(formNode, nodes);

    const fields: FormFieldInfo[] = [];
    let primaryAction: string | null = null;
    const secondaryActions: string[] = [];

    for (const descendant of allDescendants) {
      if (isInputField(descendant)) {
        fields.push(nodeToFormField(descendant));
      } else if (isPrimaryAction(descendant)) {
        primaryAction = descendant.id;
      } else if (isSecondaryAction(descendant)) {
        secondaryActions.push(descendant.id);
      }
    }

    if (fields.length > 0) {
      formCounter++;
      forms.push({
        id: `form_${String(formCounter)}`,
        label: formNode.name ?? formNode.text,
        fields,
        primaryAction,
        secondaryActions,
      });
    }
  }

  // If no explicit forms found, look for implicit form groups
  if (forms.length === 0) {
    const inputNodes = nodes.filter(
      (n) => isInputField(n) && n.visible,
    );

    if (inputNodes.length >= 2) {
      const fields = inputNodes.map(nodeToFormField);
      const submitBtn = nodes.find(
        (n) => isPrimaryAction(n) && n.visible,
      );

      formCounter++;
      forms.push({
        id: `form_${String(formCounter)}`,
        label: "form",
        fields,
        primaryAction: submitBtn?.id ?? null,
        secondaryActions: [],
      });
    }
  }

  return forms;
}

function collectDescendants(
  parent: UiNode,
  allNodes: readonly UiNode[],
): UiNode[] {
  const result: UiNode[] = [];
  const queue = [...parent.children];

  while (queue.length > 0) {
    const childId = queue.shift();
    if (childId === undefined) continue;
    const child = allNodes.find((n) => n.id === childId);
    if (child === undefined) continue;
    result.push(child);
    queue.push(...child.children);
  }

  return result;
}

function isInputField(node: UiNode): boolean {
  const inputTypes = new Set([
    "textbox",
    "input",
    "textarea",
    "select",
    "checkbox",
    "radio",
    "searchbox",
    "combobox",
  ]);
  return inputTypes.has(node.type) || inputTypes.has(node.role);
}

function isPrimaryAction(node: UiNode): boolean {
  if (!node.clickable) return false;
  const text = (node.text + " " + (node.name ?? "")).toLowerCase();
  const primaryPatterns = [
    "submit",
    "sign in",
    "log in",
    "login",
    "continue",
    "next",
    "send",
    "save",
    "confirm",
    "pay",
    "buy",
    "place order",
  ];
  return primaryPatterns.some((p) => text.includes(p));
}

function isSecondaryAction(node: UiNode): boolean {
  if (!node.clickable) return false;
  const text = (node.text + " " + (node.name ?? "")).toLowerCase();
  const secondaryPatterns = [
    "cancel",
    "back",
    "forgot",
    "reset",
    "skip",
    "later",
    "no thanks",
  ];
  return secondaryPatterns.some((p) => text.includes(p));
}

function nodeToFormField(node: UiNode): FormFieldInfo {
  return {
    inputNodeId: node.id,
    label: node.name ?? node.placeholder ?? node.text,
    required: false,
    fieldType: inferFieldType(node),
    value: node.value,
    validationError: null,
  };
}

function inferFieldType(node: UiNode): string {
  const name = (node.name ?? "").toLowerCase();
  const placeholder = (node.placeholder ?? "").toLowerCase();
  const combined = name + " " + placeholder;

  if (combined.includes("email")) return "email";
  if (combined.includes("password") || combined.includes("passcode"))
    return "password";
  if (combined.includes("phone") || combined.includes("tel")) return "phone";
  if (combined.includes("search")) return "search";
  if (node.type === "checkbox" || node.role === "checkbox") return "checkbox";
  if (node.type === "radio" || node.role === "radio") return "radio";
  if (node.type === "select" || node.role === "combobox") return "select";

  return "text";
}
