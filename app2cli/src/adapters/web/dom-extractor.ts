import type { UiNode } from "../../core/schema/index.js";

/**
 * Raw DOM node structure as extracted from the browser.
 * Used by both the Playwright adapter and golden fixture tests.
 */
export interface RawWebNode {
  tag: string;
  text: string;
  role: string;
  ariaLabel: string | null;
  ariaDescribedby: string | null;
  placeholder: string | null;
  href: string | null;
  type: string | null;
  value: string | null;
  disabled: boolean;
  hidden: boolean;
  checked: boolean | null;
  ariaChecked: string | null;
  ariaSelected: string | null;
  /** Explicitly detected clickability from the browser (cursor:pointer, onclick, etc.) */
  clickable?: boolean;
  bounds: { x: number; y: number; width: number; height: number } | null;
  cssSelector: string;
  children: RawWebNode[];
}

/**
 * Convert a raw web DOM tree into a flat array of normalized UiNodes.
 */
export function rawNodesToUiNodes(root: RawWebNode): UiNode[] {
  const nodes: UiNode[] = [];
  let counter = 0;

  function walk(raw: RawWebNode, path: string[]): string {
    counter++;
    const nodeId = `n_${String(counter)}`;
    const currentPath = [...path, `${raw.tag}[${String(counter)}]`];
    const childIds: string[] = [];

    for (const child of raw.children) {
      childIds.push(walk(child, currentPath));
    }

    const uiNode: UiNode = {
      id: nodeId,
      type: mapType(raw),
      role: raw.role,
      text: raw.text,
      name: raw.ariaLabel,
      description: raw.ariaDescribedby,
      value: raw.value,
      placeholder: raw.placeholder,
      enabled: !raw.disabled,
      visible: !raw.hidden,
      clickable: isClickable(raw),
      focusable: isFocusable(raw),
      checked: resolveChecked(raw),
      selected: raw.ariaSelected === "true",
      bounds: raw.bounds,
      locator: {
        web: { css: raw.cssSelector },
      },
      path: currentPath,
      children: childIds,
    };

    nodes.push(uiNode);
    return nodeId;
  }

  walk(root, []);
  return nodes;
}

function mapType(raw: RawWebNode): string {
  const typeMap: Record<string, string> = {
    button: "button",
    a: "link",
    input:
      raw.type === "checkbox"
        ? "checkbox"
        : raw.type === "radio"
          ? "radio"
          : "textbox",
    textarea: "textbox",
    select: "select",
    img: "image",
    nav: "navigation",
    h1: "heading",
    h2: "heading",
    h3: "heading",
    h4: "heading",
    h5: "heading",
    h6: "heading",
    p: "text",
    span: "text",
    div: "container",
    section: "container",
    main: "container",
    form: "form",
    label: "label",
    li: "listitem",
    ul: "list",
    ol: "list",
    table: "table",
    dialog: "dialog",
  };
  return typeMap[raw.tag] ?? "container";
}

function isClickable(raw: RawWebNode): boolean {
  // Use browser-detected clickability if available (cursor:pointer, onclick, etc.)
  if (raw.clickable === true) return true;
  const clickableTags = new Set([
    "button",
    "a",
    "input",
    "select",
    "textarea",
  ]);
  const clickableRoles = new Set([
    "button",
    "link",
    "tab",
    "menuitem",
    "option",
  ]);
  return clickableTags.has(raw.tag) || clickableRoles.has(raw.role);
}

function isFocusable(raw: RawWebNode): boolean {
  const focusableTags = new Set([
    "button",
    "a",
    "input",
    "select",
    "textarea",
  ]);
  return (
    focusableTags.has(raw.tag) ||
    raw.role === "button" ||
    raw.role === "link"
  );
}

function resolveChecked(raw: RawWebNode): boolean | null {
  if (raw.checked !== null) return raw.checked;
  if (raw.ariaChecked === "true") return true;
  if (raw.ariaChecked === "false") return false;
  return null;
}
