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

// Client for the self-hosted Google Places proxy (gplaces_parser
// backend). Contract lives at gplaces_parser/FEEDBACK.md — that file
// defines the request shape, response JSON shape, auth header, and
// category slug enum. Any change on either side should be reflected
// there first to keep the two repos in lockstep.
//
// Auth: static `X-Api-Key` header. No sessions, no refresh.
@Singleton
class GPlacesClient @Inject constructor(
    @param:Named("gplacesApiUrl") private val baseUrl: String,
    @param:Named("gplacesApiKey") private val apiKey: String,
) : PlacesSource {

    private val http = OkHttpClient.Builder()
        .callTimeout(10, TimeUnit.SECONDS)
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    override val isConfigured: Boolean
        get() = baseUrl.isNotBlank() && apiKey.isNotBlank()

    override suspend fun nearbySearch(
        latitude: Double,
        longitude: Double,
        radiusMeters: Int,
        category: PlaceCategory,
        limit: Int,
    ): List<Place> = withContext(Dispatchers.IO) {
        if (!isConfigured) return@withContext emptyList()

        val url = baseUrl.trimEnd('/').let { "$it/v1/places" }.toHttpUrl()
            .newBuilder()
            .addQueryParameter("lat", latitude.toString())
            .addQueryParameter("lon", longitude.toString())
            .addQueryParameter("radius", radiusMeters.toString())
            .addQueryParameter("category", category.slug)
            .addQueryParameter("limit", limit.toString())
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
                    Timber.w("gplaces HTTP %d", response.code)
                    return@use emptyList<Place>()
                }
                val body = response.body?.string() ?: return@use emptyList<Place>()
                parseResponse(body, category, latitude, longitude)
            }
        }.onFailure {
            Timber.w(it, "gplaces lookup failed")
        }.getOrNull() ?: emptyList()
    }

    // Exposed so the parser test can drive it against canned JSON.
    // The parser is permissive: any required-field-missing or malformed
    // entry is skipped, not failed. Sorting trusts the server but we
    // re-sort by distance defensively — cheap and saves debugging a
    // rogue upstream ordering later.
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
            val id = item.optStringOrNull("id") ?: continue
            val name = item.optStringOrNull("name") ?: continue
            val lat = item.optDouble("lat", Double.NaN)
            val lon = item.optDouble("lon", Double.NaN)
            if (lat.isNaN() || lon.isNaN()) continue

            // optString on a JSON null returns the *string* "null" on
            // Android's org.json — optStringOrNull filters that out
            // along with blanks so the UI never renders the literal.
            val address = item.optStringOrNull("address")
            val phone = item.optStringOrNull("phone")
            val rating = if (item.has("rating") && !item.isNull("rating")) {
                item.optDouble("rating", Double.NaN).toFloat().takeIf { !it.isNaN() }
            } else null
            val reviewCount = if (item.has("review_count") && !item.isNull("review_count")) {
                item.optInt("review_count", -1).takeIf { it >= 0 }
            } else null
            val openNow = if (item.has("open_now") && !item.isNull("open_now")) {
                item.optBoolean("open_now", false)
            } else null
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
                rating = rating,
                reviewCount = reviewCount,
                openNow = openNow,
            )
        }
        return out.sortedBy { it.distanceMeters }
    }

    private companion object {
        const val USER_AGENT = "omono/0.x (personal sideload; https://apps.omarss.net)"
    }
}

// `optString("field")` returns "null" (the word) when the JSON value
// is null — a gotcha specific to Android's org.json. Filter the
// literal plus empty string so callers always get real content or
// a real null.
private fun JSONObject.optStringOrNull(key: String): String? {
    if (!has(key) || isNull(key)) return null
    return optString(key).takeIf { it.isNotBlank() && it != "null" }
}

// Stable lowercase-snake slug used in the `category` query param.
// Keep in sync with the enum in FEEDBACK.md — that's the server-side
// contract. Renaming here without renaming there will produce 400s.
val PlaceCategory.slug: String
    get() = when (this) {
        PlaceCategory.COFFEE -> "coffee"
        PlaceCategory.RESTAURANT -> "restaurant"
        PlaceCategory.FAST_FOOD -> "fast_food"
        PlaceCategory.BAKERY -> "bakery"
        PlaceCategory.GROCERY -> "grocery"
        PlaceCategory.MALL -> "mall"
        PlaceCategory.FUEL -> "fuel"
        PlaceCategory.EV_CHARGER -> "ev_charger"
        PlaceCategory.CAR_WASH -> "car_wash"
        PlaceCategory.PHARMACY -> "pharmacy"
        PlaceCategory.HOSPITAL -> "hospital"
        PlaceCategory.GYM -> "gym"
        PlaceCategory.PARK -> "park"
        PlaceCategory.BANK -> "bank"
        PlaceCategory.ATM -> "atm"
        PlaceCategory.MOSQUE -> "mosque"
        PlaceCategory.SALON -> "salon"
        PlaceCategory.LAUNDRY -> "laundry"
        PlaceCategory.POST_OFFICE -> "post_office"
    }
