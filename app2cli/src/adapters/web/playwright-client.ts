import { chromium } from "playwright-core";
import type { Browser, BrowserContext, Page } from "playwright-core";
import { withRetry } from "../../core/retry.js";
import type { Screen, UiNode } from "../../core/schema/index.js";
import { assignStableIds } from "../../core/stable-id.js";
import type { PlatformAdapter } from "../types.js";
import type { RawWebNode } from "./dom-extractor.js";
import { rawNodesToUiNodes } from "./dom-extractor.js";

/**
 * Options for the Playwright web adapter.
 */
export interface PlaywrightClientOptions {
  /** CDP endpoint URL for connecting to an existing browser */
  cdpUrl?: string;
  /** Viewport width (default: 1280) */
  viewportWidth?: number;
  /** Viewport height (default: 720) */
  viewportHeight?: number;
  /** Whether to run headless (default: true) */
  headless?: boolean;
}

/**
 * Web adapter using Playwright + Chromium.
 * Extracts DOM structure, accessibility tree, and performs actions.
 */
export class PlaywrightClient implements PlatformAdapter {
  readonly platform = "web" as const;

  private browser: Browser | null = null;
  private context: BrowserContext | null = null;
  private page: Page | null = null;
  private readonly options: PlaywrightClientOptions;

  constructor(options: PlaywrightClientOptions = {}) {
    this.options = options;
  }

  async connect(target: string, _options?: { packageName?: string }): Promise<void> {
    const normalizedTarget = normalizeWebTarget(target);

    if (this.options.cdpUrl !== undefined) {
      this.browser = await chromium.connectOverCDP(this.options.cdpUrl);
    } else {
      this.browser = await chromium.launch({
        headless: this.options.headless ?? true,
      });
    }

    this.context = await this.browser.newContext({
      viewport: {
        width: this.options.viewportWidth ?? 1280,
        height: this.options.viewportHeight ?? 720,
      },
    });

    this.page = await this.context.newPage();
    await this.page.goto(normalizedTarget, {
      waitUntil: "domcontentloaded",
    });
    await this.page.waitForLoadState("networkidle").catch(() => {
      // networkidle can timeout on pages with persistent connections
    });
  }

  async getScreen(): Promise<Screen> {
    const page = this.requirePage();
    const title = await page.title();
    const url = page.url();
    const viewport = page.viewportSize();

    return {
      title,
      url,
      packageName: null,
      activity: null,
      width: viewport?.width ?? 1280,
      height: viewport?.height ?? 720,
    };
  }

  async getNodes(): Promise<UiNode[]> {
    const page = this.requirePage();

    // Extract raw DOM tree inside browser context.
    // Uses a string expression to avoid esbuild/tsx injecting __name helpers
    // that don't exist in the browser runtime.
    const rawTree = await page.evaluate(EXTRACT_DOM_SCRIPT);
    const nodes = rawNodesToUiNodes(rawTree as RawWebNode);
    return assignStableIds(nodes);
  }

  async screenshot(): Promise<Buffer> {
    const page = this.requirePage();
    return Buffer.from(await page.screenshot({ fullPage: true }));
  }

  async getRawSource(): Promise<string> {
    const page = this.requirePage();
    return page.content();
  }

  async click(nodeId: string, nodes: readonly UiNode[]): Promise<void> {
    const page = this.requirePage();
    const node = nodes.find((n) => n.id === nodeId);
    if (node === undefined) {
      throw new Error(`Node ${nodeId} not found`);
    }

    await withRetry(
      async () => {
        const css = node.locator.web?.css;
        if (typeof css === "string" && css.length > 0) {
          await page.click(css, { timeout: 5000 });
        } else if (node.bounds !== null) {
          const centerX = node.bounds.x + node.bounds.width / 2;
          const centerY = node.bounds.y + node.bounds.height / 2;
          await page.mouse.click(centerX, centerY);
        } else {
          throw new Error(`No locator or bounds for node ${nodeId}`);
        }
      },
      { maxAttempts: 2, initialDelayMs: 300 },
    );
  }

  async type(
    nodeId: string,
    text: string,
    nodes: readonly UiNode[],
  ): Promise<void> {
    const page = this.requirePage();
    const node = nodes.find((n) => n.id === nodeId);
    if (node === undefined) {
      throw new Error(`Node ${nodeId} not found`);
    }

    await withRetry(
      async () => {
        const css = node.locator.web?.css;
        if (typeof css === "string" && css.length > 0) {
          await page.fill(css, text, { timeout: 5000 });
        } else if (node.bounds !== null) {
          const centerX = node.bounds.x + node.bounds.width / 2;
          const centerY = node.bounds.y + node.bounds.height / 2;
          await page.mouse.click(centerX, centerY);
          await page.keyboard.type(text);
        } else {
          throw new Error(`No locator or bounds for node ${nodeId}`);
        }
      },
      { maxAttempts: 2, initialDelayMs: 300 },
    );
  }

  async navigate(url: string): Promise<void> {
    const page = this.requirePage();
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => {
      // networkidle can timeout on pages with persistent connections
    });
  }

  async disconnect(): Promise<void> {
    if (this.page !== null) {
      await this.page.close().catch(() => undefined);
      this.page = null;
    }
    if (this.context !== null) {
      await this.context.close().catch(() => undefined);
      this.context = null;
    }
    if (this.browser !== null) {
      await this.browser.close().catch(() => undefined);
      this.browser = null;
    }
  }

  private requirePage(): Page {
    if (this.page === null) {
      throw new Error(
        "Not connected. Call connect() before using the adapter.",
      );
    }
    return this.page;
  }
}

const SUPPORTED_WEB_TARGET_PROTOCOLS = new Set(["http:", "https:"]);

export function normalizeWebTarget(target: string): string {
  let parsed: URL;

  try {
    parsed = new URL(target);
  } catch {
    throw new Error(`Invalid web target URL: ${target}`);
  }

  if (!SUPPORTED_WEB_TARGET_PROTOCOLS.has(parsed.protocol)) {
    throw new Error(
      `Unsupported web target protocol: ${parsed.protocol}`,
    );
  }

  return parsed.toString();
}

/**
 * Browser-context DOM extraction script.
 *
 * This MUST be a string, not a function reference. When using tsx/esbuild in dev mode,
 * function references get transformed with __name() helpers that don't exist in the
 * browser context, causing "ReferenceError: __name is not defined".
 *
 * A string expression is passed verbatim to page.evaluate() without transformation.
 */
const EXTRACT_DOM_SCRIPT = `(() => {
  let idCounter = 0;

  function walk(el) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const isVisible =
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      rect.width > 0 &&
      rect.height > 0;
    const lines = (el.innerText || "").split("\\n");
    const firstLine = (lines[0] || "").trim();

    // Detect clickability beyond just semantic tags:
    // framework-rendered sites use divs with click handlers, cursor:pointer, etc.
    const isClickable = detectClickable(el, style);

    return {
      tag: el.tagName.toLowerCase(),
      text: firstLine,
      role: el.getAttribute("role") || inferRole(el, isClickable),
      ariaLabel: el.getAttribute("aria-label"),
      ariaDescribedby: el.getAttribute("aria-describedby"),
      placeholder: el.getAttribute("placeholder"),
      href: el.getAttribute("href"),
      type: el.getAttribute("type"),
      value: el.value != null ? el.value : null,
      disabled: el.hasAttribute("disabled"),
      hidden: !isVisible,
      checked: typeof el.checked === "boolean" ? el.checked : null,
      ariaChecked: el.getAttribute("aria-checked"),
      ariaSelected: el.getAttribute("aria-selected"),
      clickable: isClickable,
      bounds: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      cssSelector: buildCssSelector(el),
      children: Array.from(el.children).map(walk),
      _id: ++idCounter,
    };
  }

  function detectClickable(el, style) {
    var tag = el.tagName.toLowerCase();
    // Natively clickable elements
    if (tag === "a" || tag === "button" || tag === "input" || tag === "select" || tag === "textarea") return true;
    // ARIA roles that indicate clickability
    var role = el.getAttribute("role");
    if (role === "button" || role === "link" || role === "tab" || role === "menuitem" || role === "option") return true;
    // Has onclick or framework click handlers
    if (el.hasAttribute("onclick") || el.hasAttribute("ng-click") || el.hasAttribute("data-click")) return true;
    // tabindex makes element focusable/clickable
    if (el.hasAttribute("tabindex") && el.getAttribute("tabindex") !== "-1") return true;
    // cursor:pointer is a strong signal of clickability
    if (style.cursor === "pointer") return true;
    return false;
  }

  function inferRole(el, isClickable) {
    var tag = el.tagName.toLowerCase();
    var inputType = el.getAttribute("type") || "text";
    var inputRoleMap = {
      text: "textbox", email: "textbox", password: "textbox",
      search: "searchbox", tel: "textbox", url: "textbox",
      number: "spinbutton", checkbox: "checkbox", radio: "radio",
      submit: "button", reset: "button", button: "button", range: "slider",
    };
    var tagRoleMap = {
      button: "button", a: "link",
      input: inputRoleMap[inputType] || "textbox",
      textarea: "textbox", select: "combobox", img: "image",
      nav: "navigation", main: "main", header: "banner",
      footer: "contentinfo", form: "form",
      h1: "heading", h2: "heading", h3: "heading",
      h4: "heading", h5: "heading", h6: "heading",
      ul: "list", ol: "list", li: "listitem", dialog: "dialog",
    };
    var mapped = tagRoleMap[tag];
    if (mapped) return mapped;
    // Infer role from clickability for non-semantic elements
    if (isClickable) {
      if (el.getAttribute("href")) return "link";
      return "button";
    }
    return "generic";
  }

  function buildCssSelector(el) {
    var id = el.getAttribute("id");
    if (id && id.length > 0) return "#" + id;
    var testId = el.getAttribute("data-testid") || el.getAttribute("data-test-id");
    if (testId && testId.length > 0) return '[data-testid="' + testId + '"]';
    var tag = el.tagName.toLowerCase();
    var name = el.getAttribute("name");
    if (name && name.length > 0) return tag + '[name="' + name + '"]';
    var type = el.getAttribute("type");
    if (type && type.length > 0) return tag + '[type="' + type + '"]';
    return tag;
  }

  return walk(document.documentElement);
})()` as const;
