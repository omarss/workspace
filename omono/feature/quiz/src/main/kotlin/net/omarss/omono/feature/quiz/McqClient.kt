package net.omarss.omono.feature.quiz

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import timber.log.Timber
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Named
import javax.inject.Singleton

// HTTP client for the `/v1/mcq/*` endpoints on `api.omarss.net`. The
// mcqs service shares the same base URL and API key as gplaces (see
// omono/FEEDBACK.md §10.1–10.2) so we reuse the `@Named("gplacesApiUrl")`
// and `@Named("gplacesApiKey")` providers rather than wiring a second
// set of properties through `local.properties`.
//
// All endpoints return 200 on success; transport failures bubble up
// as nulls and the repository treats them as "try again later". No
// retry / backoff wired here — the UI surfaces errors and the user
// retaps Start.
@Singleton
class McqClient @Inject constructor(
    @param:Named("gplacesApiUrl") private val baseUrl: String,
    @param:Named("gplacesApiKey") private val apiKey: String,
) {

    private val http = OkHttpClient.Builder()
        .callTimeout(10, TimeUnit.SECONDS)
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    val isConfigured: Boolean
        get() = baseUrl.isNotBlank() && apiKey.isNotBlank()

    suspend fun subjects(): List<Subject> = withContext(Dispatchers.IO) {
        if (!isConfigured) return@withContext emptyList()
        val body = get("/v1/mcq/subjects") ?: return@withContext emptyList()
        runCatching { parseSubjects(body) }
            .onFailure { Timber.w(it, "mcq /subjects parse failed") }
            .getOrNull()
            .orEmpty()
    }

    suspend fun topics(subject: String): List<Topic> = withContext(Dispatchers.IO) {
        if (!isConfigured || subject.isBlank()) return@withContext emptyList()
        val body = get("/v1/mcq/topics") { addQueryParameter("subject", subject) }
            ?: return@withContext emptyList()
        runCatching { parseTopics(body) }
            .onFailure { Timber.w(it, "mcq /topics parse failed") }
            .getOrNull()
            .orEmpty()
    }

    suspend fun quiz(
        subjects: List<String>,
        topics: List<String>,
        type: QuestionType,
        count: Int,
    ): List<Question> = withContext(Dispatchers.IO) {
        if (!isConfigured) return@withContext emptyList()
        val body = get("/v1/mcq/quiz") {
            if (subjects.isNotEmpty()) addQueryParameter("subject", subjects.joinToString(","))
            if (topics.isNotEmpty()) addQueryParameter("topic", topics.joinToString(","))
            type.wireName?.let { addQueryParameter("type", it) }
            addQueryParameter("count", count.coerceIn(1, 50).toString())
        } ?: return@withContext emptyList()
        runCatching {
            val root = JSONObject(body)
            val arr = root.optJSONArray("questions") ?: return@runCatching emptyList()
            (0 until arr.length()).mapNotNull { i ->
                arr.optJSONObject(i)?.let(::parseQuestion)
            }
        }.onFailure { Timber.w(it, "mcq /quiz parse failed") }
            .getOrNull()
            .orEmpty()
    }

    // Fetch the same question with answers + explanation filled in.
    // Called after the user picks an option so we can reveal
    // correct/incorrect without storing answers on the client.
    suspend fun reveal(id: Int): Question? = withContext(Dispatchers.IO) {
        if (!isConfigured) return@withContext null
        val body = get("/v1/mcq/questions/$id") ?: return@withContext null
        runCatching { parseQuestion(JSONObject(body)) }
            .onFailure { Timber.w(it, "mcq /questions/$id parse failed") }
            .getOrNull()
    }

    private fun get(
        path: String,
        query: okhttp3.HttpUrl.Builder.() -> Unit = {},
    ): String? {
        val url = baseUrl.trimEnd('/').let { "$it$path" }.toHttpUrl().newBuilder()
        query(url)
        val request = Request.Builder()
            .url(url.build())
            .header("X-Api-Key", apiKey)
            .header("User-Agent", USER_AGENT)
            .get()
            .build()
        return runCatching {
            http.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    Timber.w("mcq %s HTTP %d", path, response.code)
                    return@use null
                }
                response.body?.string()
            }
        }.onFailure { Timber.w(it, "mcq %s failed", path) }
            .getOrNull()
    }

    private companion object {
        const val USER_AGENT = "omono/0.x (personal sideload; https://apps.omarss.net)"
    }
}

// --- Parsers ------------------------------------------------------
// Kept top-level and internal so unit tests can hit them without
// spinning up the HTTP layer.

internal fun parseSubjects(json: String): List<Subject> {
    val root = JSONObject(json)
    val arr = root.optJSONArray("subjects") ?: return emptyList()
    val out = ArrayList<Subject>(arr.length())
    for (i in 0 until arr.length()) {
        val item = arr.optJSONObject(i) ?: continue
        val slug = item.optString("slug").ifBlank { continue }
        val title = item.optString("title").ifBlank { slug }
        out += Subject(
            slug = slug,
            title = title,
            totalQuestions = item.optInt("total_questions", 0),
            roundsCovered = item.optInt("rounds_covered", 0),
        )
    }
    return out
}

internal fun parseTopics(json: String): List<Topic> {
    val root = JSONObject(json)
    val subject = root.optString("subject")
    val arr = root.optJSONArray("topics") ?: return emptyList()
    val out = ArrayList<Topic>(arr.length())
    for (i in 0 until arr.length()) {
        val item = arr.optJSONObject(i) ?: continue
        val slug = item.optString("slug").ifBlank { continue }
        val title = item.optString("title").ifBlank { slug }
        out += Topic(
            subject = subject,
            slug = slug,
            title = title,
            questionCount = item.optInt("question_count", 0),
        )
    }
    return out
}

internal fun parseQuestion(item: JSONObject): Question? {
    val id = item.optInt("id", -1).takeIf { it >= 0 } ?: return null
    val stem = item.optString("stem").ifBlank { return null }
    val subject = item.optString("subject")
    val type = QuestionType.fromWire(item.optString("type").ifBlank { null })
    val round = item.optInt("round", 0)
    val difficulty = item.optInt("difficulty", 0)
    val explanation = item.optString("explanation").takeIf {
        it.isNotBlank() && it != "null"
    }
    val topics = parseStringArray(item.optJSONArray("topics"))
    val options = parseOptions(item.optJSONArray("options"))
    if (options.isEmpty()) return null
    return Question(
        id = id,
        subject = subject,
        type = type,
        round = round,
        difficulty = difficulty,
        stem = stem,
        options = options,
        explanation = explanation,
        topics = topics,
    )
}

private fun parseOptions(arr: JSONArray?): List<QuizOption> {
    if (arr == null) return emptyList()
    val out = ArrayList<QuizOption>(arr.length())
    for (i in 0 until arr.length()) {
        val item = arr.optJSONObject(i) ?: continue
        val letter = item.optString("letter").ifBlank { continue }
        val text = item.optString("text")
        val isCorrect = if (item.has("is_correct") && !item.isNull("is_correct")) {
            item.optBoolean("is_correct", false)
        } else null
        out += QuizOption(letter = letter, text = text, isCorrect = isCorrect)
    }
    return out
}

private fun parseStringArray(arr: JSONArray?): List<String> {
    if (arr == null) return emptyList()
    val out = ArrayList<String>(arr.length())
    for (i in 0 until arr.length()) {
        val s = arr.optString(i).ifBlank { null } ?: continue
        out += s
    }
    return out
}
