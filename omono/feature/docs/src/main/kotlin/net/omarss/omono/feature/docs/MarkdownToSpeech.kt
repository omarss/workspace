package net.omarss.omono.feature.docs

// Converts raw Markdown into a stream of plain-text utterances the
// `android.speech.tts.TextToSpeech` engine can pronounce without
// reading every `#` as "pound", every ** as "star star", etc.
//
// Design: split into "utterances" (a block boundary we want the TTS
// engine to breathe on) rather than one giant string, so the reader
// UI can highlight the current block and skip backward/forward by
// block boundary. An utterance is one heading, one paragraph, or
// one list item — code fences are deliberately skipped because
// reading `for (i = 0; i < n; i++)` aloud helps no one.

// Strip inline markdown formatting from a single line so TTS only
// pronounces the words. Keeps the content pure text — it doesn't try
// to render anything the user sees.
internal fun stripInlineMarkdown(line: String): String {
    var s = line
    // Images — drop the alt text and the link, keep nothing.
    s = s.replace(IMAGE_RE, "")
    // Links — keep the label, drop the URL.
    s = s.replace(LINK_RE, "$1")
    // Code spans — keep the content, drop the backticks.
    s = s.replace(CODE_SPAN_RE, "$1")
    // Bold / italic markers. Order matters — two-star first so we
    // don't eat one half of `**bold**` as italic first.
    s = s.replace(BOLD_STAR_RE, "$1")
    s = s.replace(BOLD_UNDERSCORE_RE, "$1")
    s = s.replace(ITALIC_STAR_RE, "$1")
    s = s.replace(ITALIC_UNDERSCORE_RE, "$1")
    // Strikethrough ~~foo~~ — drop markers, keep text. A user who
    // strikes through something usually still wants it heard.
    s = s.replace(STRIKE_RE, "$1")
    // Collapse runs of whitespace — dropping an image leaves a
    // double space in its place, which the TTS engine reads as a
    // long pause.
    s = s.replace(WHITESPACE_RUN_RE, " ")
    return s.trim()
}

private val WHITESPACE_RUN_RE = Regex("\\s+")

private val IMAGE_RE = Regex("""!\[[^\]]*]\([^)]*\)""")
private val LINK_RE = Regex("""\[([^\]]*)]\([^)]*\)""")
private val CODE_SPAN_RE = Regex("""`([^`]+)`""")
private val BOLD_STAR_RE = Regex("""\*\*([^*]+)\*\*""")
private val BOLD_UNDERSCORE_RE = Regex("""__([^_]+)__""")
private val ITALIC_STAR_RE = Regex("""(?<!\*)\*([^*]+)\*(?!\*)""")
private val ITALIC_UNDERSCORE_RE = Regex("""(?<!_)_([^_]+)_(?!_)""")
private val STRIKE_RE = Regex("""~~([^~]+)~~""")

// Break markdown into utterances ready for TTS. Skips fenced code
// blocks entirely, drops blockquote markers, and flattens list
// bullets into plain sentences.
fun markdownToUtterances(markdown: String): List<String> {
    val out = ArrayList<String>()
    val lines = markdown.lines()
    val paragraph = StringBuilder()
    var inFence = false

    fun flushParagraph() {
        if (paragraph.isEmpty()) return
        val text = stripInlineMarkdown(paragraph.toString())
        if (text.isNotBlank()) out += text
        paragraph.clear()
    }

    for (raw in lines) {
        val line = raw.trimEnd()
        val trimmedStart = line.trimStart()
        // Toggle fenced-code state on ``` or ~~~ lines. Fenced
        // content is not spoken.
        if (trimmedStart.startsWith("```") || trimmedStart.startsWith("~~~")) {
            flushParagraph()
            inFence = !inFence
            continue
        }
        if (inFence) continue

        // Blank line → paragraph break.
        if (line.isBlank()) {
            flushParagraph()
            continue
        }

        // Heading — emit on its own utterance so the engine pauses.
        val headingMatch = HEADING_RE.matchEntire(trimmedStart)
        if (headingMatch != null) {
            flushParagraph()
            val text = stripInlineMarkdown(headingMatch.groupValues[2])
            if (text.isNotBlank()) out += text
            continue
        }

        // List item — flatten to a standalone utterance.
        val listMatch = LIST_ITEM_RE.matchEntire(trimmedStart)
        if (listMatch != null) {
            flushParagraph()
            val text = stripInlineMarkdown(listMatch.groupValues[2])
            if (text.isNotBlank()) out += text
            continue
        }

        // Blockquote — treat as a normal paragraph but strip the `>`.
        val quoted = if (trimmedStart.startsWith(">")) {
            trimmedStart.removePrefix(">").trimStart()
        } else {
            line
        }
        if (paragraph.isNotEmpty()) paragraph.append(' ')
        paragraph.append(quoted)
    }
    flushParagraph()
    return out
}

private val HEADING_RE = Regex("""^(#{1,6})\s+(.+?)\s*#*\s*$""")
private val LIST_ITEM_RE = Regex("""^(?:[-*+]|\d+\.)\s+(.*)$""").let {
    // The group indexes line up with the markdown-engine heading re
    // above so callers can treat both the same way — groupValues[2]
    // is always the text payload.
    Regex("""^((?:[-*+]|\d+\.))\s+(.*)$""")
}
