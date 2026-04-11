import { XMLParser } from "fast-xml-parser";
import type { UiNode } from "../../core/schema/index.js";

/**
 * Parsed bounds from Android's "[x1,y1][x2,y2]" format.
 */
interface AndroidBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Raw attributes from a UiAutomator XML node.
 */
interface RawAndroidNode {
  "@_text"?: string;
  "@_resource-id"?: string;
  "@_class"?: string;
  "@_package"?: string;
  "@_content-desc"?: string;
  "@_checkable"?: string;
  "@_checked"?: string;
  "@_clickable"?: string;
  "@_enabled"?: string;
  "@_focusable"?: string;
  "@_focused"?: string;
  "@_scrollable"?: string;
  "@_long-clickable"?: string;
  "@_password"?: string;
  "@_selected"?: string;
  "@_visible-to-user"?: string;
  "@_bounds"?: string;
  "@_index"?: string;
  node?: RawAndroidNode | RawAndroidNode[];
}

/**
 * Parse a UiAutomator XML dump into normalized UiNode objects.
 */
export function parseUiAutomatorXml(xml: string): UiNode[] {
  const parser = new XMLParser({
    ignoreAttributes: false,
    attributeNamePrefix: "@_",
  });

  const parsed: unknown = parser.parse(xml);
  const root = extractRoot(parsed);
  if (root === null) return [];

  const nodes: UiNode[] = [];
  let counter = 0;

  function walk(raw: RawAndroidNode, path: string[]): string {
    counter++;
    const nodeId = `n_${String(counter)}`;
    const className = raw["@_class"] ?? "";
    const currentPath = [...path, `${className}[${String(counter)}]`];
    const childIds: string[] = [];

    const children = getChildren(raw);
    for (const child of children) {
      childIds.push(walk(child, currentPath));
    }

    const bounds = parseBounds(raw["@_bounds"] ?? "");
    const resourceId = raw["@_resource-id"] ?? "";
    const contentDesc = raw["@_content-desc"] ?? "";
    const text = raw["@_text"] ?? "";

    const uiNode: UiNode = {
      id: nodeId,
      type: mapAndroidType(className),
      role: mapAndroidRole(className),
      text,
      name: contentDesc.length > 0 ? contentDesc : null,
      description: null,
      value: text.length > 0 ? text : null,
      placeholder: null,
      enabled: raw["@_enabled"] === "true",
      visible: raw["@_visible-to-user"] !== "false",
      clickable: raw["@_clickable"] === "true",
      focusable: raw["@_focusable"] === "true",
      checked: raw["@_checkable"] === "true" ? raw["@_checked"] === "true" : null,
      selected: raw["@_selected"] === "true",
      bounds,
      locator: {
        android: {
          resourceId: resourceId.length > 0 ? resourceId : undefined,
          contentDesc: contentDesc.length > 0 ? contentDesc : undefined,
          className: className.length > 0 ? className : undefined,
        },
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

/**
 * Extract the root node from parsed XML.
 * Handles both hierarchy-wrapped and direct node formats.
 */
interface ParsedXmlRoot {
  hierarchy?: {
    node?: RawAndroidNode;
  };
  node?: RawAndroidNode;
}

function extractRoot(parsed: unknown): RawAndroidNode | null {
  if (typeof parsed !== "object" || parsed === null) return null;

  const obj = parsed as ParsedXmlRoot;

  // Standard uiautomator dump: { hierarchy: { node: ... } }
  if (obj.hierarchy !== undefined) {
    if (obj.hierarchy.node !== undefined) {
      return obj.hierarchy.node;
    }
    // Empty hierarchy (no child nodes)
    return null;
  }

  // Direct node at root
  if (obj.node !== undefined) {
    return obj.node;
  }

  return null;
}

function getChildren(raw: RawAndroidNode): RawAndroidNode[] {
  if (raw.node === undefined) return [];
  if (Array.isArray(raw.node)) return raw.node;
  return [raw.node];
}

/**
 * Parse Android bounds string "[x1,y1][x2,y2]" into structured bounds.
 */
function parseBounds(boundsStr: string): AndroidBounds | null {
  const match = /\[(\d+),(\d+)\]\[(\d+),(\d+)\]/.exec(boundsStr);
  if (match === null) return null;

  const x1 = parseInt(match[1] ?? "0", 10);
  const y1 = parseInt(match[2] ?? "0", 10);
  const x2 = parseInt(match[3] ?? "0", 10);
  const y2 = parseInt(match[4] ?? "0", 10);

  return {
    x: x1,
    y: y1,
    width: x2 - x1,
    height: y2 - y1,
  };
}

/**
 * Map Android widget class to a semantic type.
 */
function mapAndroidType(className: string): string {
  const shortName = className.split(".").pop() ?? className;
  const typeMap: Record<string, string> = {
    Button: "button",
    ImageButton: "button",
    FloatingActionButton: "button",
    MaterialButton: "button",
    AppCompatButton: "button",
    TextView: "text",
    AppCompatTextView: "text",
    EditText: "textbox",
    AppCompatEditText: "textbox",
    TextInputEditText: "textbox",
    AutoCompleteTextView: "textbox",
    ImageView: "image",
    AppCompatImageView: "image",
    CheckBox: "checkbox",
    AppCompatCheckBox: "checkbox",
    RadioButton: "radio",
    Switch: "checkbox",
    SwitchCompat: "checkbox",
    ToggleButton: "checkbox",
    Spinner: "select",
    RecyclerView: "list",
    ListView: "list",
    ScrollView: "container",
    NestedScrollView: "container",
    LinearLayout: "container",
    RelativeLayout: "container",
    FrameLayout: "container",
    ConstraintLayout: "container",
    CoordinatorLayout: "container",
    ViewPager: "container",
    ViewPager2: "container",
    TabLayout: "tabs",
    BottomNavigationView: "navigation",
    NavigationBarView: "navigation",
    Toolbar: "navigation",
    ActionBar: "navigation",
    SearchView: "searchbox",
    WebView: "container",
    ProgressBar: "progressbar",
    SeekBar: "slider",
  };

  return typeMap[shortName] ?? "container";
}

/**
 * Map Android widget class to a semantic role.
 */
function mapAndroidRole(className: string): string {
  const shortName = className.split(".").pop() ?? className;
  const roleMap: Record<string, string> = {
    Button: "button",
    ImageButton: "button",
    FloatingActionButton: "button",
    TextView: "text",
    EditText: "textbox",
    ImageView: "image",
    CheckBox: "checkbox",
    RadioButton: "radio",
    Switch: "switch",
    Spinner: "combobox",
    RecyclerView: "list",
    ListView: "list",
    TabLayout: "tablist",
    BottomNavigationView: "navigation",
    NavigationBarView: "navigation",
    Toolbar: "toolbar",
    SearchView: "searchbox",
    ProgressBar: "progressbar",
    SeekBar: "slider",
  };

  return roleMap[shortName] ?? "generic";
}
