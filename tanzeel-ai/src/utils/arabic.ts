const TASHKEEL_RE =
  /[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7-\u06E8\u06EA-\u06ED]/g;
const TATWEEL = "\u0640";

const ALEF_VARIANTS = ["إ", "أ", "آ", "ٱ"];

export function normalizeArabic(text: string): string {
  // Remove tashkeel (diacritics)
  let normalized = text.replace(TASHKEEL_RE, "");
  // Remove tatweel
  normalized = normalized.replace(new RegExp(TATWEEL, "g"), "");
  // Normalize alef variants to plain alef
  for (const c of ALEF_VARIANTS) {
    normalized = normalized.replaceAll(c, "ا");
  }
  // Taa marbuta -> haa
  normalized = normalized.replaceAll("ة", "ه");
  // Alef maqsura -> yaa
  normalized = normalized.replaceAll("ى", "ي");
  // Waw hamza -> waw
  normalized = normalized.replaceAll("ؤ", "و");
  // Yaa hamza -> yaa
  normalized = normalized.replaceAll("ئ", "ي");
  // Normalize whitespace
  normalized = normalized.replace(/\s+/g, " ").trim();
  return normalized;
}
