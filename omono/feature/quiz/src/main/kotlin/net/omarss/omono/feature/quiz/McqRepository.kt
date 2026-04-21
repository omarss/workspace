package net.omarss.omono.feature.quiz

import javax.inject.Inject
import javax.inject.Singleton

// Thin pass-through repository — the client already returns pure
// domain types, so there's nothing to translate here. Kept as a
// distinct seam so the ViewModel depends on a feature-facing
// interface rather than the HTTP client itself, and future caching
// / offline handling can drop in behind it without touching the
// ViewModel.
@Singleton
class McqRepository @Inject constructor(
    private val client: McqClient,
) {
    val isConfigured: Boolean get() = client.isConfigured

    suspend fun subjects(): List<Subject> = client.subjects()

    suspend fun topics(subject: String): List<Topic> = client.topics(subject)

    suspend fun quiz(
        subjects: List<String>,
        topics: List<String>,
        type: QuestionType,
        count: Int,
    ): List<Question> = client.quiz(subjects, topics, type, count)

    suspend fun reveal(id: Int): Question? = client.reveal(id)
}
