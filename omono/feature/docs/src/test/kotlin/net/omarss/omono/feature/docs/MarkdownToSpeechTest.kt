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
        stripInlineMarkdown("before ![alt](/img.png) after") shouldBe "before after"
    }

    @Test
    fun `a blank-label link becomes literal link`() {
        stripInlineMarkdown("see []( https://foo.com )") shouldBe "see link"
    }

    @Test
    fun `bare urls in prose collapse to domain`() {
        stripInlineMarkdown("deploy to https://api.omarss.net/v1/roads now") shouldBe
            "deploy to link to api.omarss.net now"
        stripInlineMarkdown("docs at www.kubernetes.io/docs") shouldBe
            "docs at link to kubernetes.io"
    }

    @Test
    fun `acronyms expand to spelled letters`() {
        // API, URL, HTTP are the core ones.
        stripInlineMarkdown("Hit the API via HTTP") shouldBe "Hit the A P I via H T T P"
        // Substring matches inside identifiers must NOT fire.
        stripInlineMarkdown("call api_key") shouldBe "call api_key"
    }

    @Test
    fun `kubernetes numeronym is spoken as the word`() {
        stripInlineMarkdown("run on k8s") shouldBe "run on kubernetes"
    }

    @Test
    fun `utterances carry structural pause after each block`() {
        val md = """
            # Title

            A paragraph.

            - item one
            - item two
        """.trimIndent()
        val us = markdownToUtterances(md)
        us shouldHaveSize 4
        us[0] shouldBe Utterance("Title", silenceAfterMs = 700L)
        us[1] shouldBe Utterance("A paragraph.", silenceAfterMs = 400L)
        us[2] shouldBe Utterance("item one", silenceAfterMs = 250L)
        us[3] shouldBe Utterance("item two", silenceAfterMs = 250L)
    }

    @Test
    fun `utterances summarise fenced code blocks instead of reading them`() {
        val md = """
            Before.

            ```kotlin
            val x = 1
            val y = 2
            ```

            After.
        """.trimIndent()
        val us = markdownToUtterances(md)
        us shouldHaveSize 3
        us[0].text shouldBe "Before."
        us[1].text shouldBe "2-line kotlin code example, skipping"
        us[2].text shouldBe "After."
    }

    @Test
    fun `fenced code without a language tag still summarises`() {
        val md = "Before.\n\n```\nanything\n```\n\nAfter."
        val us = markdownToUtterances(md)
        us shouldHaveSize 3
        us[1].text shouldBe "1-line code example, skipping"
    }

    @Test
    fun `yaml frontmatter is stripped before parsing`() {
        val md = "---\ntitle: Hello\ndraft: false\n---\n\n# Real heading\n\nBody."
        val us = markdownToUtterances(md)
        us shouldHaveSize 2
        us[0].text shouldBe "Real heading"
        us[1].text shouldBe "Body."
    }

    @Test
    fun `ordered list markers become ordinal words`() {
        val md = "1. apple\n2. banana\n3. cherry"
        val us = markdownToUtterances(md)
        us shouldHaveSize 3
        us[0].text shouldBe "first, apple"
        us[1].text shouldBe "second, banana"
        us[2].text shouldBe "third, cherry"
    }

    @Test
    fun `mkdocs admonition flattens to prose`() {
        val md = "!!! note Heads up\n    This is important."
        val us = markdownToUtterances(md)
        us shouldHaveSize 1
        us[0].text shouldBe "Note — Heads up. This is important."
    }

    @Test
    fun `long paragraph splits on sentence boundaries`() {
        // Needs to exceed MAX_PARAGRAPH_CHARS (240) before the
        // splitter kicks in — short prose stays as one utterance.
        val long = (
            "This is the first sentence of a much longer run of prose that ought to push the total character count comfortably past the splitter threshold. " +
                "And here comes the second one with extra filler to keep the accumulated length climbing above the short-paragraph floor. " +
                "Then a third follows in the same vein, carrying enough additional words to be a standalone sentence chunk on its own. " +
                "Finally the fourth wraps it up with a distinct closing clause so the splitter has four candidate boundaries to work with."
            )
        check(long.length > 240) { "test precondition: input must exceed MAX_PARAGRAPH_CHARS" }
        val us = markdownToUtterances(long)
        check(us.size >= 3) { "expected >=3 chunks, got ${us.size}" }
        // All but the last carry the shorter inter-sentence pause.
        for (u in us.dropLast(1)) check(u.silenceAfterMs == 120L)
    }

    @Test
    fun `utterances flatten blockquotes into one paragraph`() {
        val md = "> this was said\n> then this"
        val us = markdownToUtterances(md)
        us shouldHaveSize 1
        us[0].text shouldBe "this was said then this"
    }

    @Test
    fun `domain extraction trims trailing punctuation`() {
        extractDomain("https://foo.com/bar.") shouldBe "foo.com"
        extractDomain("https://foo.com/bar),") shouldBe "foo.com"
        extractDomain("www.kubernetes.io") shouldBe "kubernetes.io"
    }
}
