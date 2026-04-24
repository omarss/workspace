package net.omarss.omono.feature.docs

import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.shouldBe
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

// Parsers hit org.json — Android-stubbed on raw JVM, so Robolectric
// supplies the real implementation. Matches the pattern used by
// feature/quiz and feature/places.
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class DocsClientTest {

    @Test
    fun `parses a subjects list with doc_count`() {
        val json = """
            {
              "subjects": [
                {"slug": "argocd", "title": "ArgoCD", "doc_count": 12},
                {"slug": "pnpm", "title": "pnpm", "doc_count": 4}
              ]
            }
        """.trimIndent()
        val subjects = parseSubjects(json)
        subjects shouldHaveSize 2
        subjects[0] shouldBe DocSubject(slug = "argocd", title = "ArgoCD", docCount = 12)
        subjects[1].docCount shouldBe 4
    }

    @Test
    fun `subjects default doc_count to -1 when server hasnt migrated yet`() {
        // Per FEEDBACK.md §11.8 the client must tolerate the existing
        // /v1/mcq/subjects shape that doesn't include doc_count yet —
        // the docs tab still renders, it just hides the count.
        val json = """
            {"subjects": [{"slug": "argocd", "title": "ArgoCD"}]}
        """.trimIndent()
        val subjects = parseSubjects(json)
        subjects shouldHaveSize 1
        subjects[0].docCount shouldBe -1
    }

    @Test
    fun `ignores subject rows missing a slug`() {
        val json = """
            {"subjects": [{"title": "no-slug-here"}, {"slug": "argocd", "title": "ArgoCD"}]}
        """.trimIndent()
        val subjects = parseSubjects(json)
        subjects shouldHaveSize 1
        subjects[0].slug shouldBe "argocd"
    }

    @Test
    fun `parses a docs list`() {
        val json = """
            {
              "subject": "argocd",
              "docs": [
                {
                  "id": "getting-started",
                  "title": "Getting started",
                  "path": "docs/getting-started.md",
                  "size_bytes": 5823,
                  "updated_at": "2026-04-21T02:11:07Z"
                },
                {
                  "id": "rollouts",
                  "title": "Rollouts"
                }
              ]
            }
        """.trimIndent()
        val docs = parseDocList(json)
        docs shouldHaveSize 2
        docs[0] shouldBe DocSummary(
            subject = "argocd",
            id = "getting-started",
            title = "Getting started",
            path = "docs/getting-started.md",
            sizeBytes = 5823L,
            updatedAt = "2026-04-21T02:11:07Z",
        )
        docs[1].path shouldBe null
        docs[1].sizeBytes shouldBe null
        docs[1].updatedAt shouldBe null
    }

    @Test
    fun `docs list without a subject field is dropped`() {
        val json = """{"docs": [{"id": "x", "title": "x"}]}"""
        parseDocList(json) shouldHaveSize 0
    }

    @Test
    fun `parses a single doc with markdown body`() {
        val json = """
            {
              "id": "getting-started",
              "subject": "argocd",
              "title": "Getting started",
              "path": "docs/getting-started.md",
              "markdown": "# Getting started\n\nArgoCD watches a Git repo.",
              "size_bytes": 42,
              "updated_at": "2026-04-21T02:11:07Z"
            }
        """.trimIndent()
        val doc = parseDoc(json)
        doc shouldBe Doc(
            subject = "argocd",
            id = "getting-started",
            title = "Getting started",
            path = "docs/getting-started.md",
            sizeBytes = 42L,
            updatedAt = "2026-04-21T02:11:07Z",
            markdown = "# Getting started\n\nArgoCD watches a Git repo.",
        )
    }

    @Test
    fun `doc without subject or id is dropped`() {
        parseDoc("""{"markdown": "hi"}""") shouldBe null
        parseDoc("""{"subject": "x", "markdown": "hi"}""") shouldBe null
    }
}
