import { z } from "zod/v4";

/**
 * Metadata about the current screen being inspected.
 */
export const ScreenSchema = z.object({
  /** Page title or activity label */
  title: z.string(),

  /** Current URL (web only) */
  url: z.string().nullable(),

  /** Android package name (android only) */
  packageName: z.string().nullable(),

  /** Android activity name (android only) */
  activity: z.string().nullable(),

  /** Viewport or screen width in pixels */
  width: z.number(),

  /** Viewport or screen height in pixels */
  height: z.number(),
});

export type Screen = z.infer<typeof ScreenSchema>;
