package net.omarss.omono.feature.twitter

import javax.inject.Inject
import javax.inject.Named
import javax.inject.Singleton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import timber.log.Timber
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException
import java.util.concurrent.TimeUnit

// OkHttp + org.json client for the homelab tweets service.
//
// Mirrors GPlacesClient in shape: short timeouts (this is feed
// content, the user is waiting), `runCatching` at the call site so a
// failed fetch returns an empty list rather than crashing the UI, and
// a feature-scoped User-Agent so any future server-side rate-limiting
// can distinguish app traffic from curl pokes.
//
// isConfigured is false when the base URL was never set (empty
// BuildConfig value because local.properties didn't define
// tweets.api.url). The repository propagates that so the UI can show
// a "not configured" empty state pointing at the README, rather than
// a generic network error.
@Singleton
class TweetsClient @Inject constructor(
    @param:Named("tweetsApiUrl") private val baseUrl: String,
) : TweetsSource {

    override val isConfigured: Boolean = baseUrl.isNotBlank()

    private val http = OkHttpClient.Builder()
        .callTimeout(8, TimeUnit.SECONDS)
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS)
        .build()

    override suspend fun feed(request: FeedRequest): FeedPage {
        if (!isConfigured) return FeedPage(emptyList())
        val base = baseUrl.toHttpUrlOrNull() ?: run {
            Timber.w("tweets.api.url is not a valid URL: %s", baseUrl)
            return FeedPage(emptyList())
        }
        val builder = base.newBuilder().addPathSegment("tweets")
        if (request.countries.isNotEmpty()) {
            builder.addQueryParameter(
                "country",
                request.countries.joinToString(",") { it.code },
            )
        }
        if (request.cities.isNotEmpty()) {
            builder.addQueryParameter("city", request.cities.joinToString(","))
        }
        request.cursor?.takeIf { it.isNotBlank() }
            ?.let { builder.addQueryParameter("cursor", it) }
        if (request.limit > 0) {
            builder.addQueryParameter("limit", request.limit.toString())
        }
        val httpReq = Request.Builder()
            .url(builder.build())
            .header("User-Agent", USER_AGENT)
            .get()
            .build()

        return withContext(Dispatchers.IO) {
            runCatching {
                http.newCall(httpReq).execute().use { response ->
                    if (!response.isSuccessful) {
                        Timber.w("tweets HTTP %d", response.code)
                        return@use FeedPage(emptyList())
                    }
                    val body = response.body?.string()
                        ?: return@use FeedPage(emptyList())
                    parsePage(body)
                }
            }.onFailure {
                Timber.w(it, "tweets fetch failed")
            }.getOrNull() ?: FeedPage(emptyList())
        }
    }

    // Parsers are `internal` so the feature module's unit tests can
    // drive them directly without an HTTP server stand-in.
    internal fun parsePage(json: String): FeedPage {
        val root = runCatching { JSONObject(json) }.getOrNull() ?: return FeedPage(emptyList())
        val arr: JSONArray = root.optJSONArray("tweets") ?: return FeedPage(emptyList())
        val out = ArrayList<Tweet>(arr.length())
        for (i in 0 until arr.length()) {
            val tweet = arr.optJSONObject(i) ?: continue
            val parsed = parseTweet(tweet) ?: continue
            out += parsed
        }
        val cursor = root.optString("next_cursor").ifBlank { null }
        return FeedPage(out, cursor)
    }

    // Kept for backward-compat with the existing Robolectric tests
    // that drive parse(json) → List<Tweet>.
    internal fun parse(json: String): List<Tweet> = parsePage(json).tweets

    private fun parseTweet(obj: JSONObject): Tweet? {
        val id = obj.optString("id").takeIf { it.isNotBlank() } ?: return null
        val text = obj.optString("text").takeIf { it.isNotBlank() } ?: return null
        val countryCode = obj.optString("country").ifBlank { null }
        val country = Country.fromCode(countryCode) ?: return null
        val createdAtRaw = obj.optString("created_at").ifBlank { null }
        val createdAtMillis = parseTimestamp(createdAtRaw) ?: return null
        // event_categories is a JSON array; convert to a Kotlin list.
        val cats = obj.optJSONArray("event_categories")?.let { arr ->
            (0 until arr.length()).mapNotNull { idx -> arr.optString(idx).ifBlank { null } }
        }.orEmpty()
        return Tweet(
            id = id,
            author = obj.optString("author"),
            handle = obj.optString("handle"),
            text = text,
            createdAtMillis = createdAtMillis,
            lang = obj.optString("lang").ifBlank { null },
            place = obj.optString("place").ifBlank { null },
            country = country,
            replyCount = obj.optInt("reply_count"),
            likeCount = obj.optInt("like_count"),
            retweetCount = obj.optInt("retweet_count"),
            spamScore = obj.optDouble("spam_score", 0.0).toFloat().coerceIn(0f, 1f),
            eventScore = obj.optDouble("event_score", 0.0).toFloat().coerceIn(0f, 1f),
            eventCategories = cats,
            avatarUrl = obj.optString("avatar_url").ifBlank { null },
        )
    }

    private fun parseTimestamp(raw: String?): Long? {
        if (raw.isNullOrBlank()) return null
        // RFC3339 with offset is what the Go service emits. Parse via
        // OffsetDateTime so any future timezone changes upstream don't
        // silently shift the displayed time.
        return runCatching {
            OffsetDateTime.parse(raw).toInstant().toEpochMilli()
        }.getOrElse { err ->
            if (err is DateTimeParseException) {
                Timber.w("could not parse created_at=%s", raw)
            }
            null
        }
    }

    private companion object {
        const val USER_AGENT = "omono-twitter/1.0"
    }
}
