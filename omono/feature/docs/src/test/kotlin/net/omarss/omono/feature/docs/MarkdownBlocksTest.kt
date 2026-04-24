package net.omarss.omono.feature.docs

import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.shouldBe
import org.junit.Test

// Pure-Kotlin parser, no Android dependency — plain JUnit runner.
class MarkdownBlocksTest {

    @Test
    fun `headings carry level`() {
        val blocks = parseMarkdownBlocks("# Title\n\n## Sub\n\n#### Deep")
        blocks shouldHaveSize 3
        blocks[0] shouldBe MarkdownBlock.Heading(level = 1, text = "Title")
        blocks[1] shouldBe MarkdownBlock.Heading(level = 2, text = "Sub")
        blocks[2] shouldBe MarkdownBlock.Heading(level = 4, text = "Deep")
    }

    @Test
    fun `paragraphs join consecutive non-empty lines`() {
        val md = "First line.\nSecond line.\n\nOther para."
        val blocks = parseMarkdownBlocks(md)
        blocks shouldHaveSize 2
        blocks[0] shouldBe MarkdownBlock.Paragraph("First line. Second line.")
        blocks[1] shouldBe MarkdownBlock.Paragraph("Other para.")
    }

    @Test
    fun `fenced code blocks capture language and body verbatim`() {
        val md = """
            para

            ```kotlin
            val x = 1
            fun y() = x
            ```

            done
        """.trimIndent()
        val blocks = parseMarkdownBlocks(md)
        blocks shouldHaveSize 3
        val code = blocks[1]
        check(code is MarkdownBlock.CodeBlock)
        code.language shouldBe "kotlin"
        code.code shouldBe "val x = 1\nfun y() = x"
    }

    @Test
    fun `list items are separate blocks and track ordering`() {
        val md = """
            - apple
            - banana
            1. one
            2. two
        """.trimIndent()
        val blocks = parseMarkdownBlocks(md)
        blocks shouldHaveSize 4
        (blocks[0] as MarkdownBlock.ListItem).ordered shouldBe false
        (blocks[0] as MarkdownBlock.ListItem).text shouldBe "apple"
        (blocks[2] as MarkdownBlock.ListItem).ordered shouldBe true
        (blocks[3] as MarkdownBlock.ListItem).text shouldBe "two"
    }

    @Test
    fun `quotes collapse into a single block per run`() {
        val md = "> line one\n> line two\n\npara"
        val blocks = parseMarkdownBlocks(md)
        blocks shouldHaveSize 2
        blocks[0] shouldBe MarkdownBlock.Quote("line one\nline two")
    }

    @Test
    fun `unclosed fence still emits what was collected`() {
        val md = "```\nstuff\nmore"
        val blocks = parseMarkdownBlocks(md)
        blocks shouldHaveSize 1
        val code = blocks[0] as MarkdownBlock.CodeBlock
        code.code shouldBe "stuff\nmore"
    }
}
