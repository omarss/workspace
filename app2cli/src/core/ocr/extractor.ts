import Tesseract from "tesseract.js";
import type { UiNode } from "../schema/index.js";

/**
 * OCR extraction options.
 */
export interface OcrOptions {
  /** Tesseract language (default: "eng") */
  language?: string;
  /** Minimum confidence to include a word (0-100, default: 60) */
  minConfidence?: number;
}

/**
 * Extract text and bounding boxes from a screenshot using Tesseract OCR.
 *
 * This is the last-resort extraction path, used when:
 * - The page is canvas/WebGL-rendered with no accessible DOM
 * - An Android view has no accessibility info
 * - The UI hierarchy is empty or unusable
 *
 * Returns UiNode objects with type "ocr_text" so downstream consumers
 * know these came from OCR, not the structured UI tree.
 */
export async function extractWithOcr(
  imageInput: Buffer | string,
  options: OcrOptions = {},
): Promise<OcrResult> {
  const language = options.language ?? "eng";
  const minConfidence = options.minConfidence ?? 60;

  const result = await Tesseract.recognize(imageInput, language);

  const nodes: UiNode[] = [];
  const rawWords: OcrWord[] = [];
  let counter = 0;

  const blocks = result.data.blocks ?? [];
  for (const block of blocks) {
    for (const paragraph of block.paragraphs) {
      for (const line of paragraph.lines) {
        // Group words into a single line node
        const lineText = line.words.map((w) => w.text).join(" ");
        const lineConfidence = line.confidence;

        if (lineConfidence < minConfidence) continue;
        if (lineText.trim().length === 0) continue;

        counter++;
        const nodeId = `n_ocr_${String(counter)}`;

        nodes.push({
          id: nodeId,
          type: "ocr_text",
          role: "text",
          text: lineText,
          name: null,
          description: null,
          value: null,
          placeholder: null,
          enabled: true,
          visible: true,
          clickable: false,
          focusable: false,
          checked: null,
          selected: false,
          bounds: {
            x: Math.round(line.bbox.x0),
            y: Math.round(line.bbox.y0),
            width: Math.round(line.bbox.x1 - line.bbox.x0),
            height: Math.round(line.bbox.y1 - line.bbox.y0),
          },
          locator: {},
          path: [`ocr_line[${String(counter)}]`],
          children: [],
        });

        // Also collect individual words for fine-grained access
        for (const word of line.words) {
          if (word.confidence >= minConfidence) {
            rawWords.push({
              text: word.text,
              confidence: word.confidence,
              bounds: {
                x: Math.round(word.bbox.x0),
                y: Math.round(word.bbox.y0),
                width: Math.round(word.bbox.x1 - word.bbox.x0),
                height: Math.round(word.bbox.y1 - word.bbox.y0),
              },
            });
          }
        }
      }
    }
  }

  return {
    nodes,
    words: rawWords,
    fullText: result.data.text,
    confidence: result.data.confidence,
  };
}

/**
 * Result of an OCR extraction.
 */
export interface OcrResult {
  /** UiNode objects extracted from OCR (type: "ocr_text") */
  nodes: UiNode[];
  /** Individual word-level results for fine-grained access */
  words: OcrWord[];
  /** Full text as a single string */
  fullText: string;
  /** Overall confidence score (0-100) */
  confidence: number;
}

export interface OcrWord {
  text: string;
  confidence: number;
  bounds: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
}
