package net.omarss.omono.feature.speed

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

// Client for the self-hosted `/v1/roads` endpoint on api.omarss.net.
// Point-in-polygon lookup against ~110 k Riyadh road polygons; returns
// the list of roads that contain the requested GPS fix, ordered by
// highway class then polygon area. Contract lives in FEEDBACK.md §6.
//
// Auth shape is identical to GPlacesClient: same host, same
// `X-Api-Key` header, same @Named credentials. A new @Singleton
// instead of reusing GPlacesClient because the places client is tied
// to the Places feature module (DI can only see its own surface).
@Singleton
class RoadsClient @Inject constructor(
    @param:Named("gplacesApiUrl") private val baseUrl: String,
    @param:Named("gplacesApiKey") private val apiKey: String,
) {

    private val http = OkHttpClient.Builder()
        // The endpoint spec promises ~20–40 ms typical; the generous
        // timeouts are to avoid mis-flagging a momentary mobile-signal
        // blip as a lookup failure while driving.
        .callTimeout(8, TimeUnit.SECONDS)
        .connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(6, TimeUnit.SECONDS)
        .build()

    val isConfigured: Boolean
        get() = baseUrl.isNotBlank() && apiKey.isNotBlank()

    // Fetches the ordered list of road candidates containing (lat, lon).
    // Returns `null` on any error (misconfiguration, network, HTTP
    // non-2xx, parse failure) so the caller can fall back to the
    // offline asset without branching on exceptions.
    suspend fun roadsAt(
        lat: Double,
        lon: Double,
        limit: Int = 5,
        // `snap_m` tells the server to return the nearest road when
        // the exact point lies off every polygon. Set to 0 to keep
        // strict exact-contains behaviour (what the old asset did).
        snapMetres: Int = DEFAULT_SNAP_M,
    ): List<RoadCandidate>? = withContext(Dispatchers.IO) {
        if (!isConfigured) return@withContext null

        val url = baseUrl.trimEnd('/').let { "$it/v1/roads" }.toHttpUrl()
            .newBuilder()
            .addQueryParameter("lat", lat.toString())
            .addQueryParameter("lon", lon.toString())
            .addQueryParameter("limit", limit.toString())
            .apply {
                if (snapMetres > 0) addQueryParameter("snap_m", snapMetres.toString())
            }
            .build()

        val request = Request.Builder()
            .url(url)
            .header("X-Api-Key", apiKey)
            .header("User-Agent", USER_AGENT)
            .get()
            .build()

        runCatching {
            http.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    Timber.w("roads HTTP %d", response.code)
                    return@use null
                }
                val body = response.body?.string() ?: return@use null
                parseResponse(body)
            }
        }.onFailure { Timber.w(it, "roads lookup failed") }
            .getOrNull()
    }

    // Exposed for unit tests so canned JSON can drive the parser
    // without spinning up a network client.
    internal fun parseResponse(json: String): List<RoadCandidate>? {
        val root = runCatching { JSONObject(json) }.getOrNull() ?: return null
        val arr: JSONArray = root.optJSONArray("roads") ?: return emptyList()
        val out = ArrayList<RoadCandidate>(arr.length())
        for (i in 0 until arr.length()) {
            val item = arr.optJSONObject(i) ?: continue
            val maxspeedKmh = if (item.has("maxspeed_kmh") && !item.isNull("maxspeed_kmh")) {
                item.optInt("maxspeed_kmh", -1).takeIf { it > 0 }
            } else null
            val heading = if (item.has("heading_deg") && !item.isNull("heading_deg")) {
                item.optDouble("heading_deg", Double.NaN)
                    .takeIf { !it.isNaN() }?.toFloat()
            } else null
            val snapped = if (item.has("snapped") && !item.isNull("snapped")) {
                item.optBoolean("snapped", false)
            } else false
            val snapDistance = if (item.has("snap_distance_m") && !item.isNull("snap_distance_m")) {
                item.optDouble("snap_distance_m", Double.NaN).takeIf { !it.isNaN() }
            } else null
            out += RoadCandidate(
                osmId = item.optLongOrNull("osm_id"),
                name = item.optStringOrNull("name"),
                nameEn = item.optStringOrNull("name_en"),
                highway = item.optStringOrNull("highway"),
                ref = item.optStringOrNull("ref"),
                maxspeedKmh = maxspeedKmh,
                speedSource = item.optStringOrNull("speed_source"),
                headingDeg = heading,
                snapped = snapped,
                snapDistanceM = snapDistance,
            )
        }
        return out
    }

    private companion object {
        const val USER_AGENT = "omono/0.x (personal sideload; https://apps.omarss.net)"

        // Default snap window for off-polygon fixes. 20 m absorbs
        // routine GPS wander on a divided highway without the server
        // reporting a wildly-different parallel road. Clients that
        // want strict behaviour can pass 0.
        const val DEFAULT_SNAP_M = 20
    }
}

// One candidate road for a given GPS fix. Maps 1:1 to the response
// object in FEEDBACK.md §6. Only fields omono actually consumes are
// held onto — the endpoint returns extras (lanes, oneway) that we can
// wire up later if a consumer needs them.
data class RoadCandidate(
    val osmId: Long?,
    val name: String?,
    val nameEn: String?,
    val highway: String?,
    val ref: String?,
    val maxspeedKmh: Int?,
    val speedSource: String?,
    val headingDeg: Float?,
    // True when the fix fell outside every polygon and the server
    // snapped to the nearest road within the requested `snap_m`
    // window. See FEEDBACK.md §9.5.
    val snapped: Boolean = false,
    val snapDistanceM: Double? = null,
)

// Same "null" literal trap as GPlacesClient — Android's org.json
// returns the string "null" for missing-via-optString, so filter both
// that and blanks in one place.
private fun JSONObject.optStringOrNull(key: String): String? {
    if (!has(key) || isNull(key)) return null
    return optString(key).takeIf { it.isNotBlank() && it != "null" }
}

private fun JSONObject.optLongOrNull(key: String): Long? {
    if (!has(key) || isNull(key)) return null
    return optLong(key, Long.MIN_VALUE).takeIf { it != Long.MIN_VALUE }
}
