package net.omarss.omono.feature.docs

import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.shouldBe
import org.junit.Test

// Pure-Kotlin string transforms — no Android, no Compose.
class MarkdownToSpeechTest {

    @Test
    fun `strips bold italic and code from a paragraph`() {
        stripInlineMarkdown("plain **bold** _italic_ `code`") shouldBe
            "plain bold italic code"
    }

    @Test
    fun `strips link markup and keeps label`() {
        stripInlineMarkdown("see [omono docs](https://apps.omarss.net)") shouldBe
            "see omono docs"
    }

    @Test
    fun `drops images entirely and collapses the leftover gap`() {
        // The image syntax is removed outright; the whitespace run
        // it leaves behind collapses to a single space so the TTS
        // engine doesn't read a 2-space pause.
        stripInlineMarkdown("before ![alt](/img.png) after") shouldBe "before after"
    }

    @Test
    fun `utterances treat headings and lists as separate blocks`() {
        val md = """
            # Title

            A **paragraph** here.

            - item one
            - item *two*
        """.trimIndent()
        val utterances = markdownToUtterances(md)
        utterances shouldHaveSize 4
        utterances[0] shouldBe "Title"
        utterances[1] shouldBe "A paragraph here."
        utterances[2] shouldBe "item one"
        utterances[3] shouldBe "item two"
    }

    @Test
    fun `utterances skip fenced code blocks entirely`() {
        val md = """
            Before.

            ```
            val x = 1
            ```

            After.
        """.trimIndent()
        val utterances = markdownToUtterances(md)
        utterances shouldHaveSize 2
        utterances[0] shouldBe "Before."
        utterances[1] shouldBe "After."
    }

    @Test
    fun `utterances flatten blockquotes into prose`() {
        val md = "> this was said\n> then this"
        val utterances = markdownToUtterances(md)
        utterances shouldHaveSize 1
        utterances[0] shouldBe "this was said then this"
    }
}
