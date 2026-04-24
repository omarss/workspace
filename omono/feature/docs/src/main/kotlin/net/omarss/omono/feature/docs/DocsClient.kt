package net.omarss.omono.feature.docs

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import timber.log.Timber
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Named
import javax.inject.Singleton

// HTTP client for the `/v1/mcq/docs*` endpoints on `api.omarss.net`.
// Shares the gplaces/mcqs API key and base URL (see FEEDBACK.md
// §10.1–10.2 and §11).
//
// Graceful degradation: every method returns null / empty on any
// non-200 response. That covers the "endpoint not yet deployed" case
// (server returns 404) as well as transport failures — in both cases
// the UI shows a "Docs coming soon" banner rather than an error.
@Singleton
class DocsClient @Inject constructor(
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

    // Lists the docs-bundle subjects. Shares the `/v1/mcq/subjects`
    // endpoint the quiz feature uses; we just map the response to
    // our narrower `DocSubject` shape (no rounds_covered / per-type
    // counts — the docs tab doesn't need them).
    //
    // `doc_count` (per FEEDBACK.md §11.2) is honoured when present,
    // otherwise the client falls back to a non-specific "—" display.
    suspend fun subjects(): List<DocSubject> = withContext(Dispatchers.IO) {
        if (!isConfigured) return@withContext emptyList()
        val body = get("/v1/mcq/subjects") ?: return@withContext emptyList()
        runCatching { parseSubjects(body) }
            .onFailure { Timber.w(it, "docs /subjects parse failed") }
            .getOrNull()
            .orEmpty()
    }

    // Lists docs in a single subject. Returns an empty list on:
    //   * backend not configured (no API key in local.properties)
    //   * HTTP 404 (endpoint not yet deployed, or subject missing)
    //   * transport error
    // The ViewModel keeps track of `endpointAvailable` so the UI can
    // show a "coming soon" hint on the first call when it's empty.
    suspend fun list(subject: String): List<DocSummary> = withContext(Dispatchers.IO) {
        if (!isConfigured || subject.isBlank()) return@withContext emptyList()
        val body = get("/v1/mcq/docs") { addQueryParameter("subject", subject) }
            ?: return@withContext emptyList()
        runCatching { parseDocList(body) }
            .onFailure { Timber.w(it, "docs /docs parse failed") }
            .getOrNull()
            .orEmpty()
    }

    // Fetches one doc's full markdown. `subject` and `id` are
    // path-encoded individually so a slug like `argo-cd` (no `%`)
    // round-trips without URL mangling.
    suspend fun fetch(subject: String, id: String): Doc? = withContext(Dispatchers.IO) {
        if (!isConfigured || subject.isBlank() || id.isBlank()) return@withContext null
        val body = get("/v1/mcq/docs/$subject/$id") ?: return@withContext null
        runCatching { parseDoc(body) }
            .onFailure { Timber.w(it, "docs /docs/{subject}/{id} parse failed") }
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
            .header("Accept", "application/json")
            .header("User-Agent", USER_AGENT)
            .get()
            .build()
        return runCatching {
            http.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    Timber.w("docs %s HTTP %d", path, response.code)
                    return@use null
                }
                response.body?.string()
            }
        }.onFailure { Timber.w(it, "docs %s failed", path) }
            .getOrNull()
    }

    private companion object {
        const val USER_AGENT = "omono/0.x (personal sideload; https://apps.omarss.net)"
    }
}

// --- Parsers ------------------------------------------------------
// Kept top-level and internal so unit tests can hit them without
// spinning up OkHttp.

internal fun parseSubjects(json: String): List<DocSubject> {
    val root = JSONObject(json)
    val arr = root.optJSONArray("subjects") ?: return emptyList()
    val out = ArrayList<DocSubject>(arr.length())
    for (i in 0 until arr.length()) {
        val item = arr.optJSONObject(i) ?: continue
        val slug = item.optString("slug").ifBlank { continue }
        val title = item.optString("title").ifBlank { slug }
        // Per FEEDBACK §11.2, `doc_count` is the new field the
        // backend adds alongside the existing MCQ fields. Default to
        // -1 so the UI can distinguish "server hasn't reported
        // doc_count yet" from "subject has 0 docs".
        val count = if (item.has("doc_count") && !item.isNull("doc_count")) {
            item.optInt("doc_count", -1)
        } else -1
        out += DocSubject(
            slug = slug,
            title = title,
            docCount = count,
        )
    }
    return out
}

internal fun parseDocList(json: String): List<DocSummary> {
    val root = JSONObject(json)
    val subject = root.optString("subject").ifBlank { return emptyList() }
    val arr = root.optJSONArray("docs") ?: return emptyList()
    val out = ArrayList<DocSummary>(arr.length())
    for (i in 0 until arr.length()) {
        val item = arr.optJSONObject(i) ?: continue
        val id = item.optString("id").ifBlank { continue }
        val title = item.optString("title").ifBlank { id }
        out += DocSummary(
            subject = subject,
            id = id,
            title = title,
            path = item.optString("path").takeIf { it.isNotBlank() },
            sizeBytes = if (item.has("size_bytes") && !item.isNull("size_bytes")) {
                item.optLong("size_bytes", -1L).takeIf { it >= 0 }
            } else null,
            updatedAt = item.optString("updated_at").takeIf { it.isNotBlank() },
        )
    }
    return out
}

internal fun parseDoc(json: String): Doc? {
    val root = JSONObject(json)
    val subject = root.optString("subject").ifBlank { return null }
    val id = root.optString("id").ifBlank { return null }
    val markdown = root.optString("markdown")
    val title = root.optString("title").ifBlank { id }
    return Doc(
        subject = subject,
        id = id,
        title = title,
        path = root.optString("path").takeIf { it.isNotBlank() },
        sizeBytes = if (root.has("size_bytes") && !root.isNull("size_bytes")) {
            root.optLong("size_bytes", -1L).takeIf { it >= 0 }
        } else null,
        updatedAt = root.optString("updated_at").takeIf { it.isNotBlank() },
        markdown = markdown,
    )
}
