/**
 * Re-exports the web DOM normalization from the adapter layer.
 * This keeps the normalize/ directory as the canonical import path
 * while the actual implementation lives with the web adapter.
 */
export { rawNodesToUiNodes as normalizeWebNodes } from "../../adapters/web/dom-extractor.js";
export type { RawWebNode } from "../../adapters/web/dom-extractor.js";
