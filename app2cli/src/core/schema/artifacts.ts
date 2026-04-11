import { z } from "zod/v4";

/**
 * Paths to persisted artifacts for a snapshot.
 */
export const ArtifactsSchema = z.object({
  /** Path to the screenshot image */
  screenshot: z.string().nullable(),

  /** Path to the raw source (HTML or XML) */
  rawSource: z.string().nullable(),

  /** Path to the normalized JSON output */
  normalizedSource: z.string().nullable(),
});

export type Artifacts = z.infer<typeof ArtifactsSchema>;
