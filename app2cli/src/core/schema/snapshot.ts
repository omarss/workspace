import { z } from "zod/v4";
import { ArtifactsSchema } from "./artifacts.js";
import { PatternMatchSchema } from "./pattern.js";
import { ScreenSchema } from "./screen.js";
import { SemanticObjectSchema } from "./semantic-object.js";
import { SessionSchema } from "./session.js";
import { UiNodeSchema } from "./ui-node.js";

/**
 * A complete snapshot — the canonical output of app2cli.
 * This is the unified format that both web and Android produce.
 */
export const SnapshotSchema = z.object({
  session: SessionSchema,
  screen: ScreenSchema,
  nodes: z.array(UiNodeSchema),
  patterns: z.array(PatternMatchSchema),
  semanticObjects: z.array(SemanticObjectSchema),
  artifacts: ArtifactsSchema,
});

export type Snapshot = z.infer<typeof SnapshotSchema>;
