import { z } from "zod/v4";

/**
 * Schema for a semantic object in the snapshot output.
 */
export const SemanticObjectSchema = z.object({
  id: z.string(),
  kind: z.string(),
  label: z.string(),
  nodeIds: z.array(z.string()),
  properties: z.record(z.string(), z.unknown()),
});

export type SemanticObjectEntry = z.infer<typeof SemanticObjectSchema>;
