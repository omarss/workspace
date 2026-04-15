package net.omarss.omono.feature.speed

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import timber.log.Timber
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

// Looks up the legal speed limit for the road the user is currently on by
// querying OpenStreetMap via the public Overpass API. Free, no API key.
//
// Privacy note: this sends rounded coordinates to overpass-api.de. The
// rounding (~50m grid) trades accuracy for less per-second tracking
// surface, but the request still leaves the device.
//
// Caching: if the user moved less than CACHE_RADIUS_M from the last
// successful query, the cached value is returned immediately. Cuts
// network traffic to ~one query per minute on a moving vehicle.
@Singleton
class RoadSpeedLimitRepository @Inject constructor() {

    private val client = OkHttpClient.Builder()
        .callTimeout(8, TimeUnit.SECONDS)
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS)
        .build()

    private val mutex = Mutex()
    private var cacheLat: Double? = null
    private var cacheLon: Double? = null
    private var cacheValue: Float? = null

    // Returns the speed limit in km/h for the road closest to the given
    // coordinates, or null if OSM has no maxspeed tag here (small streets,
    // dirt roads, etc.). Returns null on network errors too — never throws.
    suspend fun limitKmh(lat: Double, lon: Double): Float? = mutex.withLock {
        val cachedLat = cacheLat
        val cachedLon = cacheLon
        if (cachedLat != null && cachedLon != null &&
            haversineMeters(lat, lon, cachedLat, cachedLon) < CACHE_RADIUS_M
        ) {
            return cacheValue
        }

        val fetched = runCatching { fetch(lat, lon) }
            .onFailure { Timber.w(it, "Overpass lookup failed") }
            .getOrNull()

        cacheLat = lat
        cacheLon = lon
        cacheValue = fetched
        return fetched
    }

    private suspend fun fetch(lat: Double, lon: Double): Float? = withContext(Dispatchers.IO) {
        // out tags 1 = return only the closest matching way's tags. Small
        // payload, cheap on Overpass infra.
        val query = "[out:json][timeout:6];" +
            "way(around:$QUERY_RADIUS_M,$lat,$lon)[highway][maxspeed];" +
            "out tags 1;"
        val body = ("data=" + query).toRequestBody(formUrlencoded)
        val request = Request.Builder()
            .url(OVERPASS_URL)
            .post(body)
            .header("User-Agent", USER_AGENT)
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                Timber.d("Overpass HTTP %d", response.code)
                return@withContext null
            }
            val text = response.body?.string() ?: return@withContext null
            parseMaxSpeed(text)
        }
    }

    // OSM stores maxspeed as a string tag. Most values are bare integers
    // in km/h ("60"); some carry a unit suffix ("35 mph"); a few are
    // qualitative ("walk", "none"). We accept the numeric form and
    // convert mph; everything else returns null.
    internal fun parseMaxSpeed(json: String): Float? {
        val match = MAXSPEED_RE.find(json) ?: return null
        val raw = match.groupValues[1].trim()
        val numeric = raw.takeWhile { it.isDigit() || it == '.' }.toFloatOrNull() ?: return null
        if (numeric <= 0f) return null
        val isMph = raw.contains("mph", ignoreCase = true)
        return if (isMph) numeric * MPH_TO_KMH else numeric
    }

    private fun haversineMeters(
        lat1: Double, lon1: Double, lat2: Double, lon2: Double,
    ): Double {
        val r = 6_371_000.0
        val dLat = Math.toRadians(lat2 - lat1)
        val dLon = Math.toRadians(lon2 - lon1)
        val a = sin(dLat / 2).let { it * it } +
            cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) *
            sin(dLon / 2).let { it * it }
        val c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return r * c
    }

    private val formUrlencoded = "application/x-www-form-urlencoded; charset=utf-8".toMediaType()

    private companion object {
        const val OVERPASS_URL = "https://overpass-api.de/api/interpreter"
        const val USER_AGENT = "omono/0.x (personal sideload; https://apps.omarss.net)"
        const val QUERY_RADIUS_M = 25
        const val CACHE_RADIUS_M = 50.0
        const val MPH_TO_KMH = 1.609344f
        val MAXSPEED_RE = Regex("\"maxspeed\"\\s*:\\s*\"([^\"]+)\"")
    }
}
