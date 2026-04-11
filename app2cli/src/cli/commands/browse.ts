import { Command } from "commander";
import { detectPatterns } from "../../core/patterns/index.js";
import type { UiNode } from "../../core/schema/index.js";
import { extractSemanticObjects } from "../../core/semantic/index.js";
import { cliState } from "../state.js";

/**
 * Interactive browse mode — shows page content, actionable elements, and
 * lets the user pick by number to click, type, or navigate.
 */
export function createBrowseCommand(): Command {
  return new Command("browse")
    .description("Interactive browsing: view page content, links, forms, and navigate by number")
    .action(async () => {
      const adapter = cliState.getAdapter();
      const prompt = cliState.getPromptFn();

      // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
      while (true) {
        const nodes = await adapter.getNodes();
        cliState.setNodes(nodes);
        const screen = await adapter.getScreen();
        const patterns = detectPatterns(nodes);
        const semantics = extractSemanticObjects(nodes);

        // Categorize visible elements
        const headings = nodesOf(nodes, isHeading);
        const textBlocks = nodesOf(nodes, isSubstantialText);
        const inputs = nodesOf(nodes, isInput);
        const buttons = dedup(nodesOf(nodes, isButton));
        const links = dedup(nodesOf(nodes, isLink));

        const items: BrowseItem[] = [];
        let idx = 0;

        // Page header
        const title = screen.title.length > 0 ? screen.title : "Untitled";
        process.stdout.write(`\n--- ${title} ---\n`);
        if (screen.url !== null) {
          process.stdout.write(`url: ${screen.url}\n`);
        }
        if (patterns.length > 0) {
          process.stdout.write(`patterns: ${patterns.map((p) => p.kind).join(", ")}\n`);
        }

        // Page description / main content summary
        if (headings.length > 0 || textBlocks.length > 0) {
          process.stdout.write("\n");
          for (const h of headings.slice(0, 3)) {
            process.stdout.write(`  # ${h.text}\n`);
          }
          // Show first few meaningful text blocks as page description
          const shownTexts = new Set<string>();
          for (const t of textBlocks.slice(0, 5)) {
            const text = t.text.slice(0, 120);
            if (!shownTexts.has(text) && !headings.some((h) => h.text === t.text)) {
              shownTexts.add(text);
              process.stdout.write(`  ${text}${t.text.length > 120 ? "..." : ""}\n`);
            }
          }
        }

        // Semantic forms
        const forms = semantics.filter((s) => s.kind === "form");
        if (forms.length > 0) {
          process.stdout.write("\n  Forms:\n");
          for (const form of forms) {
            process.stdout.write(`    "${form.label}" (${String(form.nodeIds.length)} fields)\n`);
          }
        }

        // Inputs
        if (inputs.length > 0) {
          process.stdout.write("\n  Inputs:\n");
          for (const node of inputs) {
            idx++;
            items.push({ index: idx, node, action: "focus" });
            const label = nodeLabel(node);
            const val = node.value !== null && node.value.length > 0 ? ` = "${truncate(node.value, 30)}"` : "";
            process.stdout.write(`    [${String(idx)}] ${label}${val}\n`);
          }
        }

        // Buttons (including clickable divs detected as buttons)
        if (buttons.length > 0) {
          process.stdout.write("\n  Buttons:\n");
          for (const node of buttons.slice(0, 20)) {
            idx++;
            items.push({ index: idx, node, action: "click" });
            process.stdout.write(`    [${String(idx)}] ${nodeLabel(node)}\n`);
          }
        }

        // Links
        if (links.length > 0) {
          process.stdout.write("\n  Links:\n");
          for (const node of links.slice(0, 25)) {
            idx++;
            items.push({ index: idx, node, action: "click" });
            process.stdout.write(`    [${String(idx)}] ${nodeLabel(node)}\n`);
          }
        }

        if (items.length === 0) {
          process.stdout.write("\n  (no interactable elements found)\n");
        }

        process.stdout.write("\n");
        const answer = await prompt("[number | url <address> | q] ");
        const trimmed = answer.trim();

        if (trimmed === "q" || trimmed === "quit" || trimmed === "exit") {
          break;
        }

        if (trimmed.startsWith("url ")) {
          const url = trimmed.slice(4).trim();
          if (adapter.navigate !== undefined) {
            await adapter.navigate(url);
            process.stdout.write(`navigated to: ${url}\n`);
          } else {
            process.stdout.write("navigate not supported on this adapter\n");
          }
          continue;
        }

        const num = parseInt(trimmed, 10);
        if (Number.isNaN(num)) {
          process.stdout.write(`unknown command: "${trimmed}"\n`);
          continue;
        }

        const selected = items.find((i) => i.index === num);
        if (selected === undefined) {
          process.stdout.write(`invalid number: ${trimmed}\n`);
          continue;
        }

        if (selected.action === "focus" && isTextInput(selected.node)) {
          const text = await prompt(`  type into "${nodeLabel(selected.node)}": `);
          if (text.length > 0) {
            await adapter.type(selected.node.id, text, nodes);
            process.stdout.write(`  typed: "${text}"\n`);
          }
        } else {
          await adapter.click(selected.node.id, nodes);
          process.stdout.write(`  clicked: ${nodeLabel(selected.node)}\n`);
          await new Promise((resolve) => {
            setTimeout(resolve, 1500);
          });
        }
      }
    });
}

// ---- Filters ----

function nodesOf(nodes: UiNode[], filter: (n: UiNode) => boolean): UiNode[] {
  return nodes.filter((n) => n.visible && filter(n));
}

/**
 * Deduplicate clickable elements: when parent and child both have the same text
 * and are both clickable, prefer the child (more specific target).
 */
function dedup(nodes: UiNode[]): UiNode[] {
  const seen = new Set<string>();
  const result: UiNode[] = [];

  // Process in reverse so children (later in flat list) are seen first,
  // then parents with same text are skipped.
  const reversed = [...nodes].reverse();
  for (const node of reversed) {
    const label = (node.text.length > 0 ? node.text : (node.name ?? "")).toLowerCase().trim();
    if (label.length === 0) continue;
    if (seen.has(label)) continue;
    seen.add(label);
    result.push(node);
  }

  return result.reverse();
}

function isHeading(n: UiNode): boolean {
  if ((n.type === "heading" || n.role === "heading") && n.text.length > 0) return true;
  // Detect heading-like elements: short text, not clickable, near the top
  if (
    !n.clickable &&
    n.text.length > 3 &&
    n.text.length < 60 &&
    n.children.length === 0 &&
    n.bounds !== null &&
    n.bounds.y < 400
  ) {
    return true;
  }
  return false;
}

/** Text blocks with substantial content (not just a single word). */
function isSubstantialText(n: UiNode): boolean {
  if (n.text.length < 20) return false;
  // Leaf nodes with meaningful text, even if inside clickable parents
  if (n.children.length === 0 && (n.type === "text" || n.role === "text" || n.role === "generic")) {
    return true;
  }
  return false;
}

function isInput(n: UiNode): boolean {
  const roles = new Set(["textbox", "searchbox", "combobox", "spinbutton"]);
  const types = new Set(["textbox", "select", "checkbox", "radio"]);
  return roles.has(n.role) || types.has(n.type);
}

function isButton(n: UiNode): boolean {
  if (!n.clickable) return false;
  // Don't duplicate links
  if (n.role === "link" || n.type === "link") return false;
  // Only treat as a button if it has short, actionable text.
  // Long text (> 50 chars) is likely a description paragraph inside a clickable card,
  // not an actual button. Show those as text content instead.
  const label = n.text.length > 0 ? n.text : (n.name ?? "");
  if (label.length === 0) return false;
  if (label.length > 50) return false;
  return true;
}

function isLink(n: UiNode): boolean {
  if (!n.clickable) return false;
  if (n.role === "link" || n.type === "link") return true;
  return false;
}

// ---- Helpers ----

interface BrowseItem {
  index: number;
  node: UiNode;
  action: "click" | "focus";
}


function nodeLabel(node: UiNode): string {
  if (node.text.length > 0) return truncate(node.text, 60);
  if (node.name !== null && node.name.length > 0) return truncate(node.name, 60);
  if (node.placeholder !== null && node.placeholder.length > 0) return `(${truncate(node.placeholder, 50)})`;
  return node.id;
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 3) + "...";
}

function isTextInput(node: UiNode): boolean {
  const types = new Set(["textbox", "searchbox"]);
  return types.has(node.type) || types.has(node.role);
}
