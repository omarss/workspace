package net.omarss.omono.feature.spending

// Folds spelling variants of the same person down to a single key so
// transfers grouped by `recipientKey(name)` aggregate across the
// transliteration differences that Saudi banks emit:
//   "MOHMMAD OSEMI" / "MUHAMMAD OSEMI" / "MOHAMMAD OSEMI" → "mhmd sm"
//   "OMAR SHABAAN" / "OMAR SHAABAAN" / "OMAR SHAABAN"    → "mr shbn"
//   "KHALED SHABAAN" / "KHALID SHAABAN"                  → "khld shbn"
//
// The technique is a consonant skeleton, adapted from the Semitic-root
// idea: vowels get stripped (Arabic transliteration vowels are unstable;
// the consonants carry the identity), then repeated consonants collapse
// to one ("AA" → "" after vowel strip; "MM" → "M"). Whitespace is folded.
//
// Limitations the caller should know about:
//   * Latin only — ASCII a–z. Arabic-script names (e.g. corporate
//     senders on incoming wires like "شركة القمة الهامة …") are
//     normalised only by whitespace + case so identical Arabic strings
//     still match each other but never collide with Latin names.
//   * `y` is kept as a consonant. "ALSAYED" and "ALSAID" are NOT
//     considered the same person — they have different consonant
//     skeletons. This is intentional: treating y as a vowel collapses
//     too many distinct names (e.g. "MAYO" → "m").
//   * No phonetic equivalences (e.g. K ≈ Q, S ≈ Z) — the user accepted
//     aggressive vowel folding but not full Soundex-style phonetics,
//     where false positives across unrelated people get worse.
//
// Same function is used for two purposes:
//   1. Owner detection — match a recipient name against the user's own
//      aliases to drop own-account moves.
//   2. Per-recipient aggregation — group repeated transfers to the same
//      person on the Transfers card.
fun recipientKey(name: String): String {
    val trimmed = name.trim()
    if (trimmed.isEmpty()) return ""

    val sb = StringBuilder(trimmed.length)
    var prevConsonant: Char? = null
    var lastWasSpace = false

    for (raw in trimmed) {
        val ch = raw.lowercaseChar()
        when {
            ch.isAsciiLetter() -> {
                if (ch in VOWELS) {
                    // Vowels drop. Don't reset prevConsonant — we want
                    // "MOHAMMAD" → drop o,a,a → m,h,m,m,d → collapse → mhmd
                    continue
                }
                if (ch == prevConsonant) {
                    // Collapse double consonants ("MM" → "M").
                    continue
                }
                sb.append(ch)
                prevConsonant = ch
                lastWasSpace = false
            }
            ch.isWhitespace() -> {
                // Single space between words; trim leading/trailing.
                if (sb.isNotEmpty() && !lastWasSpace) {
                    sb.append(' ')
                    lastWasSpace = true
                    prevConsonant = null
                }
            }
            ch.isLetter() -> {
                // Non-ASCII letter (Arabic, etc.). Pass through verbatim
                // so identical Arabic strings still match; skip the
                // skeleton logic — those scripts don't need it.
                sb.append(ch)
                prevConsonant = null
                lastWasSpace = false
            }
            else -> {
                // Punctuation, digits, symbols — treat as word
                // boundaries equivalent to whitespace. Without this,
                // "OMAR-SHABAAN" would collide the R/S consonants
                // across the hyphen and key differently from
                // "OMAR SHABAAN".
                if (sb.isNotEmpty() && !lastWasSpace) {
                    sb.append(' ')
                    lastWasSpace = true
                    prevConsonant = null
                }
            }
        }
    }

    // Strip a trailing space introduced by the whitespace branch.
    return sb.toString().trimEnd()
}

private val VOWELS = setOf('a', 'e', 'i', 'o', 'u')

private fun Char.isAsciiLetter(): Boolean = this in 'a'..'z' || this in 'A'..'Z'
