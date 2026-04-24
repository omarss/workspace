package net.omarss.omono.feature.docs

// Domain types for the docs-browsing feature. Names mirror the server
// schema in `omono/FEEDBACK.md §11` — when the contract evolves the
// lockstep rule is to update that document first, then these types
// second.

// Subject exposed on the docs tab. Same shape as the MCQ `Subject`
// but with a dedicated `docCount` field so we don't conflate "this
// subject has N questions" with "this subject has N readable docs".
data class DocSubject(
    val slug: String,
    val title: String,
    val docCount: Int,
)

// Metadata for a single doc inside a subject. Does NOT include the
// Markdown body — that arrives via `DocsClient.fetch`. Keeping the
// list response light means the subject picker can render even on a
// slow connection.
data class DocSummary(
    val subject: String,
    val id: String,
    val title: String,
    val path: String?,
    val sizeBytes: Long?,
    val updatedAt: String?,
)

// Fully-hydrated doc with body. `markdown` is the raw file content.
// The ViewModel hands it to both the Compose renderer and the TTS
// strip — the strip returns plain text for the synth so the reader
// doesn't hear `#` pronounced as "pound".
data class Doc(
    val subject: String,
    val id: String,
    val title: String,
    val path: String?,
    val sizeBytes: Long?,
    val updatedAt: String?,
    val markdown: String,
)
