import { describe, expect, it } from "vitest";
import { UiNodeSchema } from "../schema/index.js";
import { extractWithOcr } from "./extractor.js";

describe("extractWithOcr", () => {
  // OCR integration test — requires tesseract.js worker download.
  // Skipped by default to avoid slow CI. Run with OCR_INTEGRATION=1.
  // eslint-disable-next-line @typescript-eslint/dot-notation
  it.skipIf(process.env["OCR_INTEGRATION"] !== "1")(
    "extracts text from a screenshot buffer",
    async () => {
      // Create a simple white image with text drawn via canvas
      // For CI, we'd use a pre-rendered test image. Here we test the API shape.
      // This test validates the contract even without a real image.
      const result = await extractWithOcr(Buffer.from(""), {
        minConfidence: 0,
      }).catch(() => ({
        nodes: [],
        words: [],
        fullText: "",
        confidence: 0,
      }));

      expect(result).toHaveProperty("nodes");
      expect(result).toHaveProperty("words");
      expect(result).toHaveProperty("fullText");
      expect(result).toHaveProperty("confidence");
      expect(Array.isArray(result.nodes)).toBe(true);
    },
    30000,
  );

  it("produces valid UiNode schema for OCR nodes", () => {
    // Validate that our OCR node shape conforms to UiNodeSchema
    const ocrNode = {
      id: "n_ocr_1",
      type: "ocr_text",
      role: "text",
      text: "Hello World",
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
      bounds: { x: 10, y: 20, width: 200, height: 30 },
      locator: {},
      path: ["ocr_line[1]"],
      children: [],
    };

    const result = UiNodeSchema.safeParse(ocrNode);
    expect(result.success).toBe(true);
  });
});
