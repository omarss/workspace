import { Command } from "commander";
import { ArtifactWriter } from "../../core/artifacts/index.js";
import { extractWithOcr } from "../../core/ocr/index.js";
import { detectPatterns } from "../../core/patterns/index.js";
import type { Artifacts, UiNode } from "../../core/schema/index.js";
import { extractSemanticObjects } from "../../core/semantic/index.js";
import { createSession } from "../../core/session.js";
import { cliState } from "../state.js";
import {
  formatNodeList,
  formatPatterns,
  formatSemanticObjects,
  formatSnapshotJson,
} from "../output.js";

export function createInspectCommand(): Command {
  return new Command("inspect")
    .description("Inspect the current screen and list all UI nodes")
    .option("--format <fmt>", "Output format: text, json, patterns, or semantic", "text")
    .option("--ocr", "Use OCR fallback (for canvas/bitmap screens)")
    .option("--ocr-lang <lang>", "OCR language (default: eng)", "eng")
    .option("--save", "Save artifacts to disk")
    .option("--output <dir>", "Artifact output directory", "artifacts")
    .action(async (opts: InspectOptions) => {
      const adapter = cliState.getAdapter();

      let nodes: UiNode[] = await adapter.getNodes();

      // OCR fallback: if no structured nodes or explicitly requested
      if (opts.ocr === true || nodes.length === 0) {
        const screenshotBuf = await adapter.screenshot();
        const ocrResult = await extractWithOcr(screenshotBuf, {
          language: opts.ocrLang,
        });

        if (opts.ocr === true) {
          // Replace with OCR nodes
          nodes = ocrResult.nodes;
        } else {
          // Merge OCR nodes as supplementary (when tree was empty)
          nodes = [...nodes, ...ocrResult.nodes];
        }

        if (ocrResult.nodes.length > 0) {
          process.stderr.write(
            `ocr: extracted ${String(ocrResult.nodes.length)} text region(s), ` +
              `confidence: ${ocrResult.confidence.toFixed(0)}%\n`,
          );
        }
      }

      cliState.setNodes(nodes);

      const screen = await adapter.getScreen();
      const patterns = detectPatterns(nodes);
      const semanticObjects = extractSemanticObjects(nodes);

      let sessionId = cliState.getSessionId();
      if (sessionId === "") {
        const session = createSession(adapter.platform, "inspect");
        sessionId = session.id;
        cliState.setSessionId(sessionId);
      }

      const snapshot = {
        session: {
          id: sessionId,
          platform: adapter.platform,
          target: screen.url ?? screen.packageName ?? "unknown",
          timestamp: new Date().toISOString(),
        },
        screen,
        nodes,
        patterns,
        semanticObjects,
        artifacts: {
          screenshot: null,
          rawSource: null,
          normalizedSource: null,
        } as Artifacts,
      };

      if (opts.save === true) {
        const writer = new ArtifactWriter(opts.output);
        const [screenshotBuf, rawSource] = await Promise.all([
          adapter.screenshot(),
          adapter.getRawSource(),
        ]);

        snapshot.artifacts = await writer.writeAll(sessionId, {
          screenshot: screenshotBuf,
          rawSource,
          snapshot,
        });
      }

      cliState.setSnapshot(snapshot);

      switch (opts.format) {
        case "json":
          process.stdout.write(formatSnapshotJson(snapshot) + "\n");
          break;
        case "patterns":
          process.stdout.write(formatPatterns(patterns) + "\n");
          break;
        case "semantic":
          process.stdout.write(formatSemanticObjects(semanticObjects) + "\n");
          break;
        default:
          process.stdout.write(formatNodeList(nodes) + "\n");
          break;
      }
    });
}

interface InspectOptions {
  format: string;
  ocr?: boolean;
  ocrLang: string;
  save?: boolean;
  output: string;
}
