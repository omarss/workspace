import { z } from "zod/v4";

/**
 * Supported target platforms.
 */
export const PlatformSchema = z.enum(["web", "android"]);

export type Platform = z.infer<typeof PlatformSchema>;

/**
 * Session metadata — identifies a single app2cli session.
 */
export const SessionSchema = z.object({
  /** Unique session identifier, e.g. "sess_abc123" */
  id: z.string(),

  /** Target platform */
  platform: PlatformSchema,

  /** Target URL or package name */
  target: z.string(),

  /** Session creation timestamp in ISO 8601 */
  timestamp: z.string(),
});

export type Session = z.infer<typeof SessionSchema>;
