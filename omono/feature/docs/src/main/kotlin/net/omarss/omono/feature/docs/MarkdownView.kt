package net.omarss.omono.feature.docs

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp

// Compose renderer for the flat block list produced by
// `parseMarkdownBlocks`. Each block maps to one Text / Card-style
// composable; headings get typography.headlineMedium down to
// titleSmall depending on level, code fences get a surfaceVariant
// box with a monospace face, inline formatting is turned into an
// `AnnotatedString` so bold / italic / code / links all render
// inline without extra composables.
//
// `activeBlockIndex` is the TTS-highlight hook — when the reader's
// speech engine advances to block N, the reader view passes that
// index here and the block renders with a highlighted background so
// the user can visually follow along.
@Composable
fun MarkdownView(
    blocks: List<MarkdownBlock>,
    modifier: Modifier = Modifier,
    activeBlockIndex: Int? = null,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        blocks.forEachIndexed { index, block ->
            val active = activeBlockIndex == index
            when (block) {
                is MarkdownBlock.Heading -> HeadingView(block, active)
                is MarkdownBlock.Paragraph -> ParagraphView(block.text, active)
                is MarkdownBlock.CodeBlock -> CodeBlockView(block)
                is MarkdownBlock.ListItem -> ListItemView(block, active)
                is MarkdownBlock.Quote -> QuoteView(block.text, active)
            }
        }
    }
}

@Composable
private fun HeadingView(block: MarkdownBlock.Heading, active: Boolean) {
    val style = when (block.level) {
        1 -> MaterialTheme.typography.headlineMedium
        2 -> MaterialTheme.typography.titleLarge
        3 -> MaterialTheme.typography.titleMedium
        else -> MaterialTheme.typography.titleSmall
    }
    Text(
        text = block.text,
        style = style.copy(fontWeight = FontWeight.SemiBold),
        color = activeAwareColor(active),
        modifier = highlightModifier(active, Modifier.fillMaxWidth()),
    )
}

@Composable
private fun ParagraphView(text: String, active: Boolean) {
    Text(
        text = inlineMarkdown(text),
        style = MaterialTheme.typography.bodyMedium,
        color = activeAwareColor(active),
        modifier = highlightModifier(active, Modifier.fillMaxWidth()),
    )
}

@Composable
private fun ListItemView(block: MarkdownBlock.ListItem, active: Boolean) {
    Row(
        modifier = highlightModifier(active, Modifier.fillMaxWidth()),
        verticalAlignment = Alignment.Top,
    ) {
        Text(
            text = if (block.ordered) "• " else "• ",
            style = MaterialTheme.typography.bodyMedium,
            color = activeAwareColor(active),
        )
        Text(
            text = inlineMarkdown(block.text),
            style = MaterialTheme.typography.bodyMedium,
            color = activeAwareColor(active),
        )
    }
}

@Composable
private fun QuoteView(text: String, active: Boolean) {
    Row(
        modifier = highlightModifier(active, Modifier.fillMaxWidth()),
        verticalAlignment = Alignment.Top,
    ) {
        Spacer(
            modifier = Modifier
                .width(3.dp)
                .padding(vertical = 2.dp)
                .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.5f)),
        )
        Spacer(Modifier.width(8.dp))
        Text(
            text = inlineMarkdown(text),
            style = MaterialTheme.typography.bodyMedium.copy(fontStyle = FontStyle.Italic),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun CodeBlockView(block: MarkdownBlock.CodeBlock) {
    // Horizontal scroll so long lines don't force the whole reader to
    // rewrap — code is a read-exactly-this medium, not a reflow one.
    Text(
        text = block.code,
        style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .horizontalScroll(rememberScrollState())
            .padding(horizontal = 12.dp, vertical = 10.dp),
    )
}

@Composable
private fun activeAwareColor(active: Boolean): Color = if (active) {
    MaterialTheme.colorScheme.onPrimaryContainer
} else {
    LocalContentColor.current
}

@Composable
private fun highlightModifier(active: Boolean, base: Modifier): Modifier = if (active) {
    base
        .clip(RoundedCornerShape(6.dp))
        .background(MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.35f))
        .padding(horizontal = 4.dp, vertical = 2.dp)
} else {
    base
}

// ---- Inline formatter ------------------------------------------------

// Parses the supported inline markdown spans — bold, italic, code,
// strike, link — and emits an AnnotatedString so Compose renders
// them as one Text layout with mixed styles. Unknown markers fall
// through as literal text, which is the right behaviour for prose
// that e.g. uses `*` for a bullet-style emphasis we don't recognise.
internal fun inlineMarkdown(source: String): AnnotatedString = buildAnnotatedString {
    var i = 0
    while (i < source.length) {
        val c = source[i]
        when {
            // Escape `\X` — keep the next char verbatim.
            c == '\\' && i + 1 < source.length -> {
                append(source[i + 1])
                i += 2
            }
            c == '`' -> {
                val end = source.indexOf('`', startIndex = i + 1)
                if (end < 0) {
                    append(c); i++
                } else {
                    withCodeStyle { append(source.substring(i + 1, end)) }
                    i = end + 1
                }
            }
            c == '*' && source.startsWith("**", i) -> {
                val end = source.indexOf("**", startIndex = i + 2)
                if (end < 0) {
                    append("**"); i += 2
                } else {
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
                        append(inlineMarkdown(source.substring(i + 2, end)))
                    }
                    i = end + 2
                }
            }
            c == '_' && source.startsWith("__", i) -> {
                val end = source.indexOf("__", startIndex = i + 2)
                if (end < 0) {
                    append("__"); i += 2
                } else {
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
                        append(inlineMarkdown(source.substring(i + 2, end)))
                    }
                    i = end + 2
                }
            }
            c == '*' -> {
                val end = source.indexOf('*', startIndex = i + 1)
                if (end < 0) {
                    append(c); i++
                } else {
                    withStyle(SpanStyle(fontStyle = FontStyle.Italic)) {
                        append(inlineMarkdown(source.substring(i + 1, end)))
                    }
                    i = end + 1
                }
            }
            c == '~' && source.startsWith("~~", i) -> {
                val end = source.indexOf("~~", startIndex = i + 2)
                if (end < 0) {
                    append("~~"); i += 2
                } else {
                    withStyle(SpanStyle(textDecoration = TextDecoration.LineThrough)) {
                        append(inlineMarkdown(source.substring(i + 2, end)))
                    }
                    i = end + 2
                }
            }
            c == '[' -> {
                // Link: [label](url). Keep the label with an
                // underline so the user can visually spot it;
                // don't make it tappable here — the reader view
                // already opens the URL via an ACTION_VIEW in a
                // dedicated affordance.
                val closeLabel = source.indexOf(']', i + 1)
                if (closeLabel < 0 || closeLabel + 1 >= source.length ||
                    source[closeLabel + 1] != '('
                ) {
                    append(c); i++
                } else {
                    val closeUrl = source.indexOf(')', closeLabel + 2)
                    if (closeUrl < 0) {
                        append(c); i++
                    } else {
                        withStyle(
                            SpanStyle(textDecoration = TextDecoration.Underline),
                        ) {
                            append(inlineMarkdown(source.substring(i + 1, closeLabel)))
                        }
                        i = closeUrl + 1
                    }
                }
            }
            else -> {
                append(c); i++
            }
        }
    }
}

// Shortcut wrapper around AnnotatedString.Builder.withStyle for the
// inline-code case — keeps the call-site above compact.
private inline fun androidx.compose.ui.text.AnnotatedString.Builder.withCodeStyle(
    crossinline block: androidx.compose.ui.text.AnnotatedString.Builder.() -> Unit,
) {
    withStyle(
        SpanStyle(
            fontFamily = FontFamily.Monospace,
            background = Color.Unspecified, // fall back to theme if styled
        ),
    ) { block() }
}

private inline fun androidx.compose.ui.text.AnnotatedString.Builder.withStyle(
    style: SpanStyle,
    crossinline block: androidx.compose.ui.text.AnnotatedString.Builder.() -> Unit,
) {
    val mark = pushStyle(style)
    try {
        block()
    } finally {
        pop(mark)
    }
}

// Re-export of Compose's own `TextStyle` for call-sites that only
// want a SpanStyle+text pair without pulling in the full import block.
@Suppress("unused")
private val sentinel: TextStyle = TextStyle.Default
