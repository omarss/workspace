package net.omarss.omono.feature.speed

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

// A single read from a live-traffic data source for one point on the
// road. `currentSpeedKmh` / `freeFlowSpeedKmh` describe how fast
// traffic is moving right now vs. the stretch's uncongested cruising
// speed; their ratio is what the watcher uses to decide "jammed or not".
data class TrafficSample(
    val currentSpeedKmh: Float,
    val freeFlowSpeedKmh: Float,
    val confidence: Float,
    val roadClosure: Boolean,
)

// Narrow abstraction so the watcher can be unit-tested without a real
// HTTP client. The TomTom implementation is the production binding.
fun interface TrafficFlowSource {
    suspend fun sample(lat: Double, lon: Double): TrafficSample?
}

// Thin wrapper around TomTom Traffic Flow API v4 (absolute speeds,
// zoom level 10 — corresponds to ~50m road segments in their tiling).
// Endpoint documented at:
// https://developer.tomtom.com/traffic-api/documentation/traffic-flow/flow-segment-data
//
// Rate-limit aware: the watcher upstream polls at most once per 30 s
// while driving, so sustained usage stays well under the 2500/day free
// tier even combined with the TomTom places client.
@Singleton
class TomTomTrafficFlowClient @Inject constructor(
    @param:Named("tomtomApiKey") private val apiKey: String,
) : TrafficFlowSource {

    private val client = OkHttpClient.Builder()
        .callTimeout(8, TimeUnit.SECONDS)
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS)
        .build()

    val isConfigured: Boolean get() = apiKey.isNotBlank()

    override suspend fun sample(lat: Double, lon: Double): TrafficSample? =
        withContext(Dispatchers.IO) {
            if (apiKey.isBlank()) return@withContext null
            val url = BASE_URL.toHttpUrl().newBuilder()
                .addQueryParameter("point", "$lat,$lon")
                .addQueryParameter("unit", "KMPH")
                .addQueryParameter("key", apiKey)
                .build()
            val request = Request.Builder()
                .url(url)
                .header("User-Agent", USER_AGENT)
                .get()
                .build()
            runCatching {
                client.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) {
                        Timber.d("TomTom flow HTTP %d", response.code)
                        return@use null
                    }
                    val body = response.body?.string() ?: return@use null
                    parseResponse(body)
                }
            }.onFailure { Timber.w(it, "TomTom flow lookup failed") }
                .getOrNull()
        }

    // Exposed so unit tests can drive the parser directly without a
    // live network call.
    internal fun parseResponse(json: String): TrafficSample? {
        val root = runCatching { JSONObject(json) }.getOrNull() ?: return null
        val data = root.optJSONObject("flowSegmentData") ?: return null
        val current = data.optDouble("currentSpeed", Double.NaN)
        val free = data.optDouble("freeFlowSpeed", Double.NaN)
        if (current.isNaN() || free.isNaN() || free <= 0.0) return null
        val confidence = data.optDouble("confidence", 0.0).toFloat()
        val closure = data.optBoolean("roadClosure", false)
        return TrafficSample(
            currentSpeedKmh = current.toFloat(),
            freeFlowSpeedKmh = free.toFloat(),
            confidence = confidence,
            roadClosure = closure,
        )
    }

    private companion object {
        const val BASE_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
        const val USER_AGENT = "omono/0.x (personal sideload; https://apps.omarss.net)"
    }
}
