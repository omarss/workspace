import { z } from "zod/v4";

/**
 * Bounding box for a UI element on screen.
 */
export const BoundsSchema = z.object({
  x: z.number(),
  y: z.number(),
  width: z.number(),
  height: z.number(),
});

export type Bounds = z.infer<typeof BoundsSchema>;

/**
 * Platform-specific locators for re-finding an element.
 */
export const LocatorSchema = z.object({
  web: z
    .object({
      css: z.string().optional(),
      xpath: z.string().optional(),
      testId: z.string().optional(),
    })
    .optional(),
  android: z
    .object({
      resourceId: z.string().optional(),
      contentDesc: z.string().optional(),
      className: z.string().optional(),
      xpath: z.string().optional(),
    })
    .optional(),
});

export type Locator = z.infer<typeof LocatorSchema>;

/**
 * A single normalized UI node — the universal building block.
 * Both web and Android normalizers produce arrays of these.
 */
export const UiNodeSchema = z.object({
  /** Stable session-scoped identifier, e.g. "n_1" */
  id: z.string(),

  /** Semantic element type: button, textbox, link, image, text, container, etc. */
  type: z.string(),

  /** ARIA role or Android widget class mapped to a standard role */
  role: z.string(),

  /** Visible text content */
  text: z.string(),

  /** Accessible name (aria-label, contentDescription, etc.) */
  name: z.string().nullable(),

  /** Accessible description */
  description: z.string().nullable(),

  /** Current value (input fields, sliders, etc.) */
  value: z.string().nullable(),

  /** Placeholder text */
  placeholder: z.string().nullable(),

  /** Whether the element is enabled for interaction */
  enabled: z.boolean(),

  /** Whether the element is visible on screen */
  visible: z.boolean(),

  /** Whether the element accepts click/tap */
  clickable: z.boolean(),

  /** Whether the element can receive focus */
  focusable: z.boolean(),

  /** Checked state for checkboxes/radios, null if not applicable */
  checked: z.boolean().nullable(),

  /** Selected state for tabs, list items, etc. */
  selected: z.boolean(),

  /** Bounding box on screen */
  bounds: BoundsSchema.nullable(),

  /** Platform-specific locators for re-finding this element */
  locator: LocatorSchema,

  /** Path from root to this node, e.g. ["root", "main", "form", "button[1]"] */
  path: z.array(z.string()),

  /** IDs of child nodes */
  children: z.array(z.string()),
});

export type UiNode = z.infer<typeof UiNodeSchema>;
