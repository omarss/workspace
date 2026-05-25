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

    override suspend fun feed(country: Country): List<Tweet> {
        if (!isConfigured) return emptyList()
        val base = baseUrl.toHttpUrlOrNull() ?: run {
            Timber.w("tweets.api.url is not a valid URL: %s", baseUrl)
            return emptyList()
        }
        val url = base.newBuilder()
            .addPathSegment("tweets")
            .addQueryParameter("country", country.code)
            .build()
        val request = Request.Builder()
            .url(url)
            .header("User-Agent", USER_AGENT)
            .get()
            .build()

        return withContext(Dispatchers.IO) {
            runCatching {
                http.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) {
                        Timber.w("tweets HTTP %d", response.code)
                        return@use emptyList<Tweet>()
                    }
                    val body = response.body?.string()
                        ?: return@use emptyList<Tweet>()
                    parse(body)
                }
            }.onFailure {
                Timber.w(it, "tweets fetch failed")
            }.getOrNull() ?: emptyList()
        }
    }

    // Parser is `internal` so the feature module's unit tests can drive
    // it directly without an HTTP server stand-in.
    internal fun parse(json: String): List<Tweet> {
        val root = runCatching { JSONObject(json) }.getOrNull() ?: return emptyList()
        val arr: JSONArray = root.optJSONArray("tweets") ?: return emptyList()
        val out = ArrayList<Tweet>(arr.length())
        for (i in 0 until arr.length()) {
            val tweet = arr.optJSONObject(i) ?: continue
            val parsed = parseTweet(tweet) ?: continue
            out += parsed
        }
        return out
    }

    private fun parseTweet(obj: JSONObject): Tweet? {
        val id = obj.optString("id").takeIf { it.isNotBlank() } ?: return null
        val text = obj.optString("text").takeIf { it.isNotBlank() } ?: return null
        val countryCode = obj.optString("country").ifBlank { null }
        val country = Country.fromCode(countryCode) ?: return null
        val createdAtRaw = obj.optString("created_at").ifBlank { null }
        val createdAtMillis = parseTimestamp(createdAtRaw) ?: return null
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
            spamScore = obj.optDouble("spam_score", 0.0).toFloat()
                .coerceIn(0f, 1f),
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
