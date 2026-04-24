package net.omarss.omono.feature.docs

// Pure Markdown block parser. Splits raw Markdown into a flat list of
// blocks the renderer can map 1:1 onto Compose composables. Kept
// framework-free and unit-testable — no Compose / Android references.
//
// Deliberately minimal coverage:
//   * Headings (# / ## / ### / ####) with the level captured
//   * Fenced code blocks (``` … ```) — joined as-is
//   * List items (- / * / + / 1.) — each emitted as a separate block
//   * Blockquotes (> …) — joined into one paragraph per run
//   * Paragraphs — everything else, blank-line separated
//
// What we deliberately DON'T handle: tables, images, HTML passthrough,
// footnotes, nested lists. The mcqs docs bundle doesn't lean on those
// shapes, and each one would double the parser's size.

sealed interface MarkdownBlock {
    data class Heading(val level: Int, val text: String) : MarkdownBlock
    data class Paragraph(val text: String) : MarkdownBlock
    data class CodeBlock(val language: String?, val code: String) : MarkdownBlock
    data class ListItem(val ordered: Boolean, val text: String) : MarkdownBlock
    data class Quote(val text: String) : MarkdownBlock
}

fun parseMarkdownBlocks(markdown: String): List<MarkdownBlock> {
    val out = ArrayList<MarkdownBlock>()
    val lines = markdown.lines()
    val paragraph = StringBuilder()
    val quote = StringBuilder()
    val code = StringBuilder()
    var codeLang: String? = null
    var inFence = false

    fun flushParagraph() {
        if (paragraph.isEmpty()) return
        out += MarkdownBlock.Paragraph(paragraph.toString().trim())
        paragraph.clear()
    }

    fun flushQuote() {
        if (quote.isEmpty()) return
        out += MarkdownBlock.Quote(quote.toString().trim())
        quote.clear()
    }

    for (raw in lines) {
        val line = raw.trimEnd()
        val trimmedStart = line.trimStart()

        // Fenced code block. Opening fence may carry a language hint
        // (``` kotlin). Closing fence has no payload.
        if (trimmedStart.startsWith("```") || trimmedStart.startsWith("~~~")) {
            if (inFence) {
                out += MarkdownBlock.CodeBlock(codeLang, code.toString().trimEnd('\n'))
                code.clear()
                codeLang = null
                inFence = false
            } else {
                flushParagraph()
                flushQuote()
                codeLang = trimmedStart.removePrefix("```").removePrefix("~~~").trim()
                    .takeIf { it.isNotEmpty() }
                inFence = true
            }
            continue
        }
        if (inFence) {
            code.append(raw)
            code.append('\n')
            continue
        }

        if (line.isBlank()) {
            flushParagraph()
            flushQuote()
            continue
        }

        val heading = HEADING_RE.matchEntire(trimmedStart)
        if (heading != null) {
            flushParagraph()
            flushQuote()
            val level = heading.groupValues[1].length.coerceIn(1, 6)
            val text = heading.groupValues[2].trim()
            out += MarkdownBlock.Heading(level = level, text = text)
            continue
        }

        val listItem = LIST_ITEM_RE.matchEntire(trimmedStart)
        if (listItem != null) {
            flushParagraph()
            flushQuote()
            val marker = listItem.groupValues[1]
            val ordered = marker.endsWith('.')
            val text = listItem.groupValues[2].trim()
            out += MarkdownBlock.ListItem(ordered = ordered, text = text)
            continue
        }

        if (trimmedStart.startsWith(">")) {
            flushParagraph()
            if (quote.isNotEmpty()) quote.append('\n')
            quote.append(trimmedStart.removePrefix(">").trimStart())
            continue
        }

        flushQuote()
        if (paragraph.isNotEmpty()) paragraph.append(' ')
        paragraph.append(trimmedStart)
    }
    flushParagraph()
    flushQuote()
    // If we finished mid-fence (malformed doc) dump whatever we
    // collected so the user still sees it — beats swallowing the
    // last N lines silently.
    if (inFence && code.isNotEmpty()) {
        out += MarkdownBlock.CodeBlock(codeLang, code.toString().trimEnd('\n'))
    }
    return out
}

private val HEADING_RE = Regex("""^(#{1,6})\s+(.+?)\s*#*\s*$""")
private val LIST_ITEM_RE = Regex("""^([-*+]|\d+\.)\s+(.*)$""")
