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
    fun `utterances skip fenced code blocks entirely`() {
        val md = """
            Before.

            ```
            val x = 1
            ```

            After.
        """.trimIndent()
        val us = markdownToUtterances(md)
        us shouldHaveSize 2
        us[0].text shouldBe "Before."
        us[1].text shouldBe "After."
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
