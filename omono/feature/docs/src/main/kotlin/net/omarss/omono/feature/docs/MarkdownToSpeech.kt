package net.omarss.omono.feature.docs

// Converts raw Markdown into a stream of `Utterance`s ready for the
// `android.speech.tts.TextToSpeech` engine. Each utterance is a text
// payload plus the silence (ms) the player should insert *after* it,
// so the reader gets structural pauses — longer after a heading,
// shorter between list items, none between adjacent sentences — that
// a single giant `speak(markdown)` call would never produce.
//
// The text payload is already stripped of markdown syntax and passed
// through a prosody-friendly preprocessor that expands common
// acronyms (so TTS doesn't pronounce "API" as "uh-pee") and collapses
// URLs into "link" / "link to <domain>" so the engine doesn't
// deadpan a 200-character deep link character by character.

data class Utterance(
    val text: String,
    val silenceAfterMs: Long = 0L,
)

// Pause presets. Tuned by ear on a driving-ish reading speed of 180
// WPM — long enough to signal a boundary, short enough to avoid
// making the reader feel slow on short blocks.
private const val PAUSE_HEADING_MS: Long = 700L
private const val PAUSE_PARAGRAPH_MS: Long = 400L
private const val PAUSE_LIST_ITEM_MS: Long = 250L
private const val PAUSE_QUOTE_MS: Long = 400L

// Strip inline markdown formatting + URLs from a single line so TTS
// only speaks words. Exposed as internal so the Compose reader can
// reuse it for any "say what's on screen" side-channels.
internal fun stripInlineMarkdown(line: String): String {
    var s = line
    s = s.replace(IMAGE_RE, "")
    s = s.replace(LINK_RE) { m ->
        // Keep the label; drop the URL. If the label is blank (e.g.
        // bare image-in-link shape) fall back to speaking "link".
        val label = m.groupValues[1].trim()
        if (label.isEmpty()) "link" else label
    }
    s = s.replace(BARE_URL_RE) { m ->
        // Bare URL in prose → read "link to <domain>" so the listener
        // knows a reference exists without hearing the full URL.
        val domain = extractDomain(m.value)
        if (domain.isEmpty()) "link" else "link to $domain"
    }
    s = s.replace(CODE_SPAN_RE, "$1")
    s = s.replace(BOLD_STAR_RE, "$1")
    s = s.replace(BOLD_UNDERSCORE_RE, "$1")
    s = s.replace(ITALIC_STAR_RE, "$1")
    s = s.replace(ITALIC_UNDERSCORE_RE, "$1")
    s = s.replace(STRIKE_RE, "$1")
    s = expandAcronyms(s)
    s = s.replace(WHITESPACE_RUN_RE, " ")
    return s.trim()
}

// Expand the most-common acronyms in technical docs to their
// phoneme-friendly form. TTS engines vary — some say "A-P-I", some
// say "apee" — but inserting explicit spaces reliably makes them
// read the letters aloud. Words not in the map pass through.
//
// Keyed case-sensitively so `IO` (acronym) expands but `io` (as in
// `java.io`) is left alone. Whole-word matching via the regex.
private fun expandAcronyms(input: String): String {
    if (input.isEmpty()) return input
    return ACRONYM_WORD_RE.replace(input) { m ->
        ACRONYMS[m.value] ?: m.value
    }
}

// Best-effort domain extraction — return the host portion of a URL
// or the substring up to the first slash for `www.foo.com/bar`-style
// prose. Purely for display: if this returns something slightly off,
// we still say "link to <thing>" which is fine.
internal fun extractDomain(url: String): String {
    val trimmed = url.trim().trimEnd('.', ',', ')', ']', '!', '?')
    val withoutScheme = trimmed.substringAfter("://", trimmed)
    val host = withoutScheme.substringBefore('/').substringBefore('?').substringBefore('#')
    return host.removePrefix("www.")
}

private val IMAGE_RE = Regex("""!\[[^\]]*]\([^)]*\)""")
private val LINK_RE = Regex("""\[([^\]]*)]\([^)]*\)""")
private val CODE_SPAN_RE = Regex("""`([^`]+)`""")
private val BOLD_STAR_RE = Regex("""\*\*([^*]+)\*\*""")
private val BOLD_UNDERSCORE_RE = Regex("""__([^_]+)__""")
private val ITALIC_STAR_RE = Regex("""(?<!\*)\*([^*]+)\*(?!\*)""")
private val ITALIC_UNDERSCORE_RE = Regex("""(?<!_)_([^_]+)_(?!_)""")
private val STRIKE_RE = Regex("""~~([^~]+)~~""")
private val WHITESPACE_RUN_RE = Regex("\\s+")

// Bare URL in prose: scheme://host... OR www.host/... A deliberately
// small grammar — we'd rather miss an exotic URL and speak it
// verbatim than wreck a sentence that happens to contain `://` or
// `www.`. Stops at whitespace, closing paren/bracket, or sentence
// punctuation.
private val BARE_URL_RE = Regex("""(?<![(\[])(?:https?://|www\.)[^\s)\]]+""")

// Technical-docs acronym dictionary. Values are the replacement text
// the TTS engine will actually read. Adjustments worth knowing:
//   * `SQL` → "sequel" (standard industry pronunciation)
//   * `JSON` → "jason" (most engines mispronounce it as "jay-son")
//   * `k8s` → "kubernetes" (the numeronym is unreadable out loud)
//   * Spaced letter sequences ("A P I") reliably trigger per-letter
//     spelling on every major Android TTS engine.
private val ACRONYMS: Map<String, String> = mapOf(
    "API" to "A P I",
    "APIs" to "A P I s",
    "REST" to "rest",
    "URL" to "U R L",
    "URLs" to "U R L s",
    "URI" to "U R I",
    "HTTP" to "H T T P",
    "HTTPS" to "H T T P S",
    "HTML" to "H T M L",
    "CSS" to "C S S",
    "JSON" to "jason",
    "YAML" to "yamel",
    "XML" to "X M L",
    "SQL" to "sequel",
    "JS" to "J S",
    "TS" to "T S",
    "TSX" to "T S X",
    "JSX" to "J S X",
    "TTS" to "T T S",
    "STT" to "S T T",
    "UI" to "U I",
    "UX" to "U X",
    "CLI" to "C L I",
    "SDK" to "S D K",
    "IDE" to "I D E",
    "ID" to "I D",
    "IDs" to "I Ds",
    "UUID" to "U U I D",
    "OS" to "O S",
    "AWS" to "A W S",
    "GCP" to "G C P",
    "K8s" to "kubernetes",
    "k8s" to "kubernetes",
    "k3s" to "K three S",
    "RBAC" to "R-back",
    "CRD" to "C R D",
    "CRDs" to "C R Ds",
    "CI" to "C I",
    "CD" to "C D",
    "DNS" to "D N S",
    "IP" to "I P",
    "TCP" to "T C P",
    "UDP" to "U D P",
    "TLS" to "T L S",
    "SSL" to "S S L",
    "SSH" to "S S H",
    "IAM" to "I A M",
    "ACL" to "A C L",
    "JWT" to "jot",
    "OAuth" to "oh-auth",
    "PR" to "P R",
    "PRs" to "P Rs",
    "gRPC" to "G R P C",
    "PII" to "P I I",
    "SaaS" to "sass",
    "PaaS" to "pass",
    "IaaS" to "eye-ass",
    "VPC" to "V P C",
    "VPN" to "V P N",
    "LAN" to "lan",
    "MFA" to "M F A",
    "2FA" to "two F A",
)

// Whole-word match for the acronym dictionary. Word boundary on both
// sides + the acronym vocabulary is alphanumeric-only, so this
// doesn't fire on substring matches inside identifiers like
// `api_key`.
private val ACRONYM_WORD_RE = Regex("""\b(""" + ACRONYMS.keys.joinToString("|") { Regex.escape(it) } + """)\b""")

// Break markdown into utterances ready for TTS. Returns a list with
// each block's text + trailing silence tuned to the block type, so
// the player knows how long to pause before advancing.
//
// Audio-friendly transforms (all driven from rules, no network hop):
//   * YAML frontmatter (`---\n…\n---`) is stripped entirely.
//   * Fenced code blocks are summarised as "X-line code example" so
//     the listener knows one existed without hearing the characters.
//   * Ordered-list markers ("1.", "2.") become "first", "second", …
//     so the engine doesn't flatly pronounce the digits.
//   * Admonition syntax (`!!! note`, `> **Note:**`) collapses to
//     "Note — <body>" so it reads naturally.
//   * Paragraphs longer than MAX_PARAGRAPH_CHARS split on sentence
//     boundaries so the engine breathes between sentences instead
//     of racing through a 600-character wall.
fun markdownToUtterances(markdown: String): List<Utterance> {
    val out = ArrayList<Utterance>()
    val body = stripFrontmatter(markdown)
    val lines = body.lines()
    val paragraph = StringBuilder()
    var inFence = false
    var fenceLang: String? = null
    var fenceLineCount = 0

    fun emit(text: String, silenceAfterMs: Long) {
        val clean = stripInlineMarkdown(text)
        if (clean.isBlank()) return
        // Split long paragraphs on sentence boundaries so the engine
        // gets room to breathe. Only the last sub-utterance carries
        // the block-level silence; the others get a shorter
        // inter-sentence pause.
        val sentences = splitIntoSentences(clean)
        for ((i, s) in sentences.withIndex()) {
            val trailing = if (i == sentences.lastIndex) silenceAfterMs else PAUSE_SENTENCE_MS
            out += Utterance(text = s, silenceAfterMs = trailing)
        }
    }

    fun flushParagraph() {
        if (paragraph.isEmpty()) return
        emit(paragraph.toString(), PAUSE_PARAGRAPH_MS)
        paragraph.clear()
    }

    for (raw in lines) {
        val line = raw.trimEnd()
        val trimmedStart = line.trimStart()
        if (trimmedStart.startsWith("```") || trimmedStart.startsWith("~~~")) {
            flushParagraph()
            if (inFence) {
                // Closing fence — emit a one-line summary and reset.
                val summary = buildString {
                    append(fenceLineCount)
                    append("-line ")
                    fenceLang?.let { append(it).append(' ') }
                    append("code example, skipping")
                }
                out += Utterance(text = summary, silenceAfterMs = PAUSE_PARAGRAPH_MS)
                inFence = false
                fenceLang = null
                fenceLineCount = 0
            } else {
                // Opening fence — remember the language tag so the
                // summary can say "python code example" etc.
                fenceLang = trimmedStart.removePrefix("```").removePrefix("~~~")
                    .trim().takeIf { it.isNotEmpty() }
                fenceLineCount = 0
                inFence = true
            }
            continue
        }
        if (inFence) {
            fenceLineCount++
            continue
        }

        // MkDocs admonitions: `!!! note Title` opens a block, the
        // following indented lines are the body. We flatten the
        // entire admonition back to "Note — body" prose.
        val admonition = ADMONITION_OPEN_RE.matchEntire(trimmedStart)
        if (admonition != null) {
            flushParagraph()
            val kind = admonition.groupValues[1].replaceFirstChar { it.titlecase() }
            val titleRest = admonition.groupValues[2].trim()
            if (paragraph.isNotEmpty()) paragraph.append(' ')
            paragraph.append(kind).append(" — ")
            if (titleRest.isNotEmpty()) paragraph.append(titleRest).append(". ")
            continue
        }

        if (line.isBlank()) {
            flushParagraph()
            continue
        }

        val headingMatch = HEADING_RE.matchEntire(trimmedStart)
        if (headingMatch != null) {
            flushParagraph()
            emit(headingMatch.groupValues[2], PAUSE_HEADING_MS)
            continue
        }

        val listMatch = LIST_ITEM_RE.matchEntire(trimmedStart)
        if (listMatch != null) {
            flushParagraph()
            val marker = listMatch.groupValues[1]
            val bodyText = listMatch.groupValues[2]
            val spoken = if (marker.endsWith('.')) {
                val digits = marker.dropLast(1)
                val word = ORDINAL_WORDS.getOrNull(digits.toIntOrNull()?.minus(1) ?: -1)
                if (word != null) "$word, $bodyText" else bodyText
            } else {
                bodyText
            }
            emit(spoken, PAUSE_LIST_ITEM_MS)
            continue
        }

        if (trimmedStart.startsWith(">")) {
            // Blockquote. `> **Note:** xxx` is also a common
            // admonition style — detect and rewrite to
            // "Note — xxx." so it reads as prose.
            val quoteBody = trimmedStart.removePrefix(">").trimStart()
            val qAdmon = QUOTE_ADMONITION_RE.matchEntire(quoteBody)
            if (qAdmon != null) {
                if (paragraph.isNotEmpty()) paragraph.append(' ')
                paragraph.append(qAdmon.groupValues[1].replaceFirstChar { it.titlecase() })
                    .append(" — ")
                    .append(qAdmon.groupValues[2])
            } else {
                if (paragraph.isNotEmpty()) paragraph.append(' ')
                paragraph.append(quoteBody)
            }
            continue
        }

        if (paragraph.isNotEmpty()) paragraph.append(' ')
        paragraph.append(line)
    }
    flushParagraph()
    return out
}

// Strip a leading `---\n…\n---` YAML frontmatter block. Hugo and
// Jekyll docs start with one; reading the raw YAML out loud would
// surface "title:" and "draft:" values the user never needed.
internal fun stripFrontmatter(markdown: String): String {
    if (!markdown.startsWith("---")) return markdown
    val match = FRONTMATTER_RE.find(markdown) ?: return markdown
    return markdown.substring(match.range.last + 1)
}

// Split a long utterance on sentence boundaries. Only kicks in above
// MAX_PARAGRAPH_CHARS — short paragraphs get through verbatim so
// normal prose doesn't get mangled by an over-eager splitter. The
// matcher is deliberately simple (period/question/exclamation
// followed by whitespace) so it doesn't over-split on "e.g." or
// "3.14" — the worst false positive is one sentence read as two,
// which is still intelligible.
internal fun splitIntoSentences(text: String): List<String> {
    if (text.length <= MAX_PARAGRAPH_CHARS) return listOf(text)
    val out = ArrayList<String>()
    val buf = StringBuilder()
    var i = 0
    while (i < text.length) {
        val c = text[i]
        buf.append(c)
        val isTerminator = c == '.' || c == '!' || c == '?' || c == '…'
        val next = text.getOrNull(i + 1)
        val boundary = isTerminator && (next == ' ' || next == '\n' || next == null)
        if (boundary && buf.length >= MIN_SENTENCE_CHARS) {
            out += buf.toString().trim()
            buf.clear()
            // Consume the separating whitespace so the next sentence
            // starts at a word character.
            while (i + 1 < text.length && text[i + 1].isWhitespace()) i++
        }
        i++
    }
    if (buf.isNotBlank()) out += buf.toString().trim()
    return out.ifEmpty { listOf(text) }
}

private val FRONTMATTER_RE = Regex("""\A---\s*\n.*?\n---\s*(?:\n|$)""", RegexOption.DOT_MATCHES_ALL)
private val ADMONITION_OPEN_RE = Regex("""^!!!\s+(\w+)(?:\s+"?(.+?)"?)?$""")
private val QUOTE_ADMONITION_RE = Regex("""^\*\*(\w+):?\*\*\s*(.*)$""")

private val HEADING_RE = Regex("""^(#{1,6})\s+(.+?)\s*#*\s*$""")
// Two capture groups: marker + body. We read the body
// (groupValues[2]) but keep the marker as an explicit group so we
// can tell ordered-list items (`1.`, `2.`) apart from bullets.
private val LIST_ITEM_RE = Regex("""^([-*+]|\d+\.)\s+(.*)$""")

// Ordinal words indexed so ORDINAL_WORDS[n-1] reads "1." as "first".
// Capped at 10 — beyond that we fall through to the raw marker; list
// items that deep are rare and the digit reading is tolerable.
private val ORDINAL_WORDS = listOf(
    "first", "second", "third", "fourth", "fifth",
    "sixth", "seventh", "eighth", "ninth", "tenth",
)

// Sentence-splitter knobs — paragraphs longer than this are split,
// but never into fragments shorter than MIN_SENTENCE_CHARS so the
// engine still gets prosodically useful chunks.
private const val MAX_PARAGRAPH_CHARS: Int = 240
private const val MIN_SENTENCE_CHARS: Int = 40

// Silence between sentences inside a single long paragraph —
// shorter than PAUSE_PARAGRAPH_MS so the block still feels like
// one thought, not multiple.
private const val PAUSE_SENTENCE_MS: Long = 120L
