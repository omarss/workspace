package net.omarss.omono.feature.speed

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import timber.log.Timber
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

// Looks up the legal speed limit for the road the user is currently on by
// querying OpenStreetMap via the public Overpass API. Free, no API key.
//
// Candidate selection: within SEARCH_RADIUS_M of the user's position we
// ask Overpass for every highway-tagged way with a maxspeed, plus their
// geometry. Each candidate is scored by (distance-to-nearest-segment) and,
// when the user's heading is trustworthy, by how closely that segment's
// bearing aligns with the user's direction of travel. Bearings are
// compared mod 180° so bidirectional roads are treated symmetrically.
//
// Caching: if the user moved less than CACHE_RADIUS_M from the last
// successful query AND did not turn by more than CACHE_BEARING_DELTA_DEG,
// the cached value is returned immediately. The bearing delta check
// invalidates the cache at intersections where the user's turn onto a
// new road would otherwise still fall inside the 50m cache halo.
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
    private var cacheBearing: Float? = null
    private var cacheValue: Float? = null

    // Returns the speed limit in km/h for the road that best matches the
    // user's position and heading, or null if no candidate is tagged.
    // Never throws — network errors surface as null.
    suspend fun limitKmh(
        lat: Double,
        lon: Double,
        bearingDeg: Float? = null,
        bearingAccuracyDeg: Float? = null,
        speedMps: Float = 0f,
    ): Float? = mutex.withLock {
        val useBearing = isBearingTrustworthy(bearingDeg, bearingAccuracyDeg, speedMps)
        val cachedLat = cacheLat
        val cachedLon = cacheLon
        val cachedBearing = cacheBearing
        if (cachedLat != null && cachedLon != null &&
            haversineMeters(lat, lon, cachedLat, cachedLon) < CACHE_RADIUS_M &&
            !hasTurnedBeyond(cachedBearing, bearingDeg)
        ) {
            return cacheValue
        }

        val fetched = runCatching { fetch(lat, lon, if (useBearing) bearingDeg else null) }
            .onFailure { Timber.w(it, "Overpass lookup failed") }
            .getOrNull()

        cacheLat = lat
        cacheLon = lon
        cacheBearing = bearingDeg
        cacheValue = fetched
        return fetched
    }

    private suspend fun fetch(
        lat: Double,
        lon: Double,
        userBearingDeg: Float?,
    ): Float? = withContext(Dispatchers.IO) {
        // out tags geom returns each way's tag map plus the ordered list
        // of nodes describing its centreline. This is what we need to
        // compute per-segment distance and bearing locally.
        val query = "[out:json][timeout:6];" +
            "way(around:$SEARCH_RADIUS_M,$lat,$lon)[highway][maxspeed];" +
            "out tags geom;"
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
            selectBestLimit(text, lat, lon, userBearingDeg)
        }
    }

    // OSM stores maxspeed as a string tag. Most values are bare integers
    // in km/h ("60"); some carry a unit suffix ("35 mph"); a few are
    // qualitative ("walk", "none"). We accept the numeric form and
    // convert mph; everything else returns null.
    internal fun parseMaxSpeedValue(raw: String): Float? {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) return null
        val numeric = trimmed.takeWhile { it.isDigit() || it == '.' }.toFloatOrNull() ?: return null
        if (numeric <= 0f) return null
        val isMph = trimmed.contains("mph", ignoreCase = true)
        return if (isMph) numeric * MPH_TO_KMH else numeric
    }

    // Iterate the Overpass response, score each candidate way, return the
    // maxspeed of the best scoring one. Exposed internal for unit tests
    // that feed hand-crafted JSON.
    internal fun selectBestLimit(
        json: String,
        lat: Double,
        lon: Double,
        userBearingDeg: Float?,
    ): Float? {
        val root = runCatching { JSONObject(json) }.getOrNull() ?: return null
        val elements = root.optJSONArray("elements") ?: return null
        var bestScore = Double.NEGATIVE_INFINITY
        var bestLimit: Float? = null

        for (i in 0 until elements.length()) {
            val element = elements.optJSONObject(i) ?: continue
            val tags = element.optJSONObject("tags") ?: continue
            val maxspeedRaw = tags.optString("maxspeed", "")
            val maxspeed = parseMaxSpeedValue(maxspeedRaw) ?: continue

            val geometry = element.optJSONArray("geometry")
            val scored = if (geometry != null && geometry.length() >= 2) {
                scoreWay(geometry, lat, lon, userBearingDeg)
            } else {
                // Tags-only fallback: treat as uniformly distant so any
                // candidate with geometry wins, but still beats nothing.
                FALLBACK_SCORE
            }
            if (scored > bestScore) {
                bestScore = scored
                bestLimit = maxspeed
            }
        }
        return bestLimit
    }

    // Computes a 0..1 score for one candidate way. Higher = more likely
    // to be the road the user is actually on. Combines:
    //   distanceScore — 1.0 when on the road, 0.0 at MAX_DIST_M away
    //   headingScore  — 1.0 aligned, 0.0 perpendicular; collapsed mod 180°
    //                   so bidirectional roads match either travel sense
    // Heading factor is softened with HEADING_FLOOR so a geometrically-
    // closer road can still win even if it bends momentarily.
    private fun scoreWay(
        geometry: org.json.JSONArray,
        lat: Double,
        lon: Double,
        userBearingDeg: Float?,
    ): Double {
        var bestDist = Double.POSITIVE_INFINITY
        var bestSegBearing = 0.0
        for (i in 0 until geometry.length() - 1) {
            val a = geometry.optJSONObject(i) ?: continue
            val b = geometry.optJSONObject(i + 1) ?: continue
            val aLat = a.optDouble("lat", Double.NaN)
            val aLon = a.optDouble("lon", Double.NaN)
            val bLat = b.optDouble("lat", Double.NaN)
            val bLon = b.optDouble("lon", Double.NaN)
            if (aLat.isNaN() || aLon.isNaN() || bLat.isNaN() || bLon.isNaN()) continue
            val d = distanceToSegmentMeters(lat, lon, aLat, aLon, bLat, bLon)
            if (d < bestDist) {
                bestDist = d
                bestSegBearing = bearingDeg(aLat, aLon, bLat, bLon)
            }
        }
        if (bestDist.isInfinite()) return Double.NEGATIVE_INFINITY

        val distanceScore = max(0.0, 1.0 - bestDist / MAX_DIST_M)
        val headingScore = if (userBearingDeg != null) {
            val diff = angularDiffDeg(userBearingDeg.toDouble(), bestSegBearing)
            val collapsed = if (diff > 90.0) 180.0 - diff else diff
            cos(Math.toRadians(collapsed)).coerceAtLeast(0.0)
        } else {
            1.0
        }
        val headingFactor = if (userBearingDeg != null) {
            HEADING_FLOOR + (1.0 - HEADING_FLOOR) * headingScore
        } else {
            1.0
        }
        return distanceScore * headingFactor
    }

    private fun isBearingTrustworthy(
        bearingDeg: Float?,
        bearingAccuracyDeg: Float?,
        speedMps: Float,
    ): Boolean {
        if (bearingDeg == null) return false
        if (speedMps < BEARING_MIN_SPEED_MPS) return false
        val acc = bearingAccuracyDeg ?: return true
        return acc <= BEARING_MAX_UNCERTAINTY_DEG
    }

    private fun hasTurnedBeyond(prev: Float?, curr: Float?): Boolean {
        if (prev == null || curr == null) return false
        return angularDiffDeg(prev.toDouble(), curr.toDouble()) > CACHE_BEARING_DELTA_DEG
    }

    private val formUrlencoded = "application/x-www-form-urlencoded; charset=utf-8".toMediaType()

    internal companion object {
        const val OVERPASS_URL = "https://overpass-api.de/api/interpreter"
        const val USER_AGENT = "omono/0.x (personal sideload; https://apps.omarss.net)"

        // Query radius widened from 25m so the bearing filter has room
        // to reject the nearest-but-wrong road (e.g. service lane).
        const val SEARCH_RADIUS_M = 40
        const val CACHE_RADIUS_M = 50.0
        const val CACHE_BEARING_DELTA_DEG = 45.0
        const val MAX_DIST_M = 30.0
        const val BEARING_MIN_SPEED_MPS = 3.0f
        const val BEARING_MAX_UNCERTAINTY_DEG = 20.0f
        const val HEADING_FLOOR = 0.2
        const val FALLBACK_SCORE = 0.5
        const val MPH_TO_KMH = 1.609344f
    }
}

// --- Geodesy helpers (internal, reused by parser tests) -------------------

// Shortest signed absolute difference between two bearings, 0..180°.
internal fun angularDiffDeg(a: Double, b: Double): Double {
    var d = ((a - b) % 360.0 + 360.0) % 360.0
    if (d > 180.0) d = 360.0 - d
    return d
}

// Initial bearing from (lat1,lon1) to (lat2,lon2), 0..360°. Good enough
// for short segments (< 1 km) which is all OSM way segments ever are.
internal fun bearingDeg(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val phi1 = Math.toRadians(lat1)
    val phi2 = Math.toRadians(lat2)
    val dLon = Math.toRadians(lon2 - lon1)
    val y = sin(dLon) * cos(phi2)
    val x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(dLon)
    val theta = Math.toDegrees(atan2(y, x))
    return (theta + 360.0) % 360.0
}

// Great-circle distance between two WGS84 points, in metres. Haversine
// is accurate to ±0.5% — plenty for speed-limit road picking.
internal fun haversineMeters(
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

// Perpendicular distance from point p to the line segment a..b, in metres.
// Uses a local equirectangular projection centred on p — correct to well
// under a metre for segments up to a few hundred metres at any latitude
// outside the poles, which fits every OSM road segment we'll ever score.
internal fun distanceToSegmentMeters(
    pLat: Double, pLon: Double,
    aLat: Double, aLon: Double,
    bLat: Double, bLon: Double,
): Double {
    val mPerDegLat = 111_320.0
    val mPerDegLon = 111_320.0 * cos(Math.toRadians(pLat))
    val ax = (aLon - pLon) * mPerDegLon
    val ay = (aLat - pLat) * mPerDegLat
    val bx = (bLon - pLon) * mPerDegLon
    val by = (bLat - pLat) * mPerDegLat
    val dx = bx - ax
    val dy = by - ay
    val lenSq = dx * dx + dy * dy
    if (lenSq == 0.0) return sqrt(ax * ax + ay * ay)
    val t = ((-ax) * dx + (-ay) * dy) / lenSq
    val clamped = min(1.0, max(0.0, t))
    val qx = ax + clamped * dx
    val qy = ay + clamped * dy
    return sqrt(qx * qx + qy * qy).let { abs(it) }
}
