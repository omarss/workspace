package net.omarss.omono.feature.places

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
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

// Thin wrapper around TomTom Search API v2. Uses nearbySearch with a
// category filter so results are pre-scoped to e.g. coffee shops.
// Documented at:
// https://developer.tomtom.com/search-api/documentation/search-service/nearby-search
//
// The client is intentionally decoupled from any ViewModel or screen
// — it hands back domain Place objects with distance + bearing
// pre-computed so the UI layer never touches the raw JSON.
@Singleton
class TomTomSearchClient @Inject constructor(
    @param:Named("tomtomApiKey") private val apiKey: String,
) : PlacesSource {

    private val client = OkHttpClient.Builder()
        .callTimeout(10, TimeUnit.SECONDS)
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    override val isConfigured: Boolean get() = apiKey.isNotBlank()

    override suspend fun nearbySearch(
        latitude: Double,
        longitude: Double,
        radiusMeters: Int,
        category: PlaceCategory,
        limit: Int,
    ): List<Place> = withContext(Dispatchers.IO) {
        if (apiKey.isBlank()) {
            Timber.d("TomTom API key not configured — skipping nearby search")
            return@withContext emptyList()
        }

        val categoryParam = category.tomTomIds.joinToString(",")
        val url = BASE_URL.toHttpUrl().newBuilder()
            .addQueryParameter("lat", latitude.toString())
            .addQueryParameter("lon", longitude.toString())
            .addQueryParameter("radius", radiusMeters.toString())
            .addQueryParameter("limit", limit.toString())
            .addQueryParameter("categorySet", categoryParam)
            .addQueryParameter("language", "en-GB")
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
                    Timber.w("TomTom search HTTP %d", response.code)
                    return@use emptyList<Place>()
                }
                val body = response.body?.string() ?: return@use emptyList<Place>()
                parseResponse(body, category, latitude, longitude)
            }
        }.onFailure {
            Timber.w(it, "TomTom search failed")
        }.getOrNull() ?: emptyList()
    }

    // Exposed as internal so the unit test can exercise parsing
    // against canned JSON without a network round-trip.
    internal fun parseResponse(
        json: String,
        category: PlaceCategory,
        userLat: Double,
        userLon: Double,
    ): List<Place> {
        val root = runCatching { JSONObject(json) }.getOrNull() ?: return emptyList()
        val results = root.optJSONArray("results") ?: return emptyList()
        val out = mutableListOf<Place>()
        for (i in 0 until results.length()) {
            val item = results.optJSONObject(i) ?: continue
            val position = item.optJSONObject("position") ?: continue
            val lat = position.optDouble("lat", Double.NaN)
            val lon = position.optDouble("lon", Double.NaN)
            if (lat.isNaN() || lon.isNaN()) continue

            val id = item.optString("id").ifEmpty { "$lat,$lon" }
            val poi = item.optJSONObject("poi")
            val name = poi?.optString("name")?.takeIf { it.isNotBlank() }
                ?: item.optJSONObject("address")?.optString("freeformAddress")
                    ?.takeIf { it.isNotBlank() }
                ?: "Unknown"
            val phone = poi?.optString("phone")?.takeIf { it.isNotBlank() }
            val addressObj = item.optJSONObject("address")
            val address = addressObj?.optString("freeformAddress")?.takeIf { it.isNotBlank() }

            val distance = haversineMeters(userLat, userLon, lat, lon)
            val bearing = bearingDegrees(userLat, userLon, lat, lon)

            out += Place(
                id = id,
                name = name,
                category = category,
                latitude = lat,
                longitude = lon,
                distanceMeters = distance,
                bearingDegrees = bearing,
                address = address,
                phone = phone,
            )
        }
        return out.sortedBy { it.distanceMeters }
    }

    private companion object {
        const val BASE_URL = "https://api.tomtom.com/search/2/nearbySearch/.json"
        const val USER_AGENT = "omono/0.x (personal sideload; https://apps.omarss.net)"
        const val MAX_RESULTS = 25
    }
}

// Great-circle distance in meters. Accurate enough for < 50 km POIs.
internal fun haversineMeters(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val r = 6_371_000.0
    val dLat = Math.toRadians(lat2 - lat1)
    val dLon = Math.toRadians(lon2 - lon1)
    val a = sin(dLat / 2).let { it * it } +
        cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) *
        sin(dLon / 2).let { it * it }
    val c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return r * c
}

// Initial bearing from (lat1, lon1) toward (lat2, lon2) in degrees,
// normalised to [0, 360). 0° = north, 90° = east, etc.
internal fun bearingDegrees(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Float {
    val phi1 = Math.toRadians(lat1)
    val phi2 = Math.toRadians(lat2)
    val deltaLambda = Math.toRadians(lon2 - lon1)
    val y = sin(deltaLambda) * cos(phi2)
    val x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(deltaLambda)
    val theta = atan2(y, x)
    return ((Math.toDegrees(theta) + 360) % 360).toFloat()
}
