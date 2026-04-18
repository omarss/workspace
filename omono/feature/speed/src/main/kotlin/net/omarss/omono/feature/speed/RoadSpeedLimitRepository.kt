package net.omarss.omono.feature.speed

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONObject
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

// Returns the legal speed limit for the road the user is currently
// on, using a bundled OpenStreetMap extract of greater Riyadh —
// every lookup is offline. The data file lives at
// `assets/riyadh_speed_limits.json` and is regenerated from Overpass
// via `scripts/fetch-speed-limits.sh`.
//
// Selection: within SEARCH_RADIUS_M of the user's position, all
// candidate ways are scored by distance-to-nearest-segment and, when
// the user's heading is trustworthy, by how closely that segment's
// bearing aligns with the direction of travel. Bearings are
// collapsed mod 180° so bidirectional roads are treated symmetrically.
//
// Load is lazy — the first query deserialises the asset into
// compact primitive arrays. Subsequent queries are a linear scan
// with a bbox pre-filter, a few milliseconds per call on a phone.
@Singleton
class RoadSpeedLimitRepository @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    private val mutex = Mutex()
    @Volatile private var ways: Array<Way>? = null

    suspend fun limitKmh(
        lat: Double,
        lon: Double,
        bearingDeg: Float? = null,
        bearingAccuracyDeg: Float? = null,
        speedMps: Float = 0f,
    ): Float? {
        val loaded = ensureLoaded() ?: return null
        val useBearing = isBearingTrustworthy(bearingDeg, bearingAccuracyDeg, speedMps)
        return selectBestLimit(
            ways = loaded,
            lat = lat,
            lon = lon,
            userBearingDeg = if (useBearing) bearingDeg else null,
        )
    }

    private suspend fun ensureLoaded(): Array<Way>? {
        ways?.let { return it }
        return mutex.withLock {
            ways ?: runCatching {
                withContext(Dispatchers.IO) { loadWays() }
            }.onFailure {
                Timber.w(it, "failed to load bundled speed limits")
            }.getOrNull().also { ways = it }
        }
    }

    private fun loadWays(): Array<Way> {
        val json = context.assets.open(ASSET_NAME).bufferedReader().use { it.readText() }
        val root = JSONObject(json)
        val arr = root.optJSONArray("ways") ?: return emptyArray()
        val out = ArrayList<Way>(arr.length())
        for (i in 0 until arr.length()) {
            val item = arr.optJSONObject(i) ?: continue
            val maxspeed = item.optDouble("l", Double.NaN).toFloat()
            if (maxspeed.isNaN() || maxspeed <= 0f) continue
            val geom = item.optJSONArray("g") ?: continue
            val nPoints = geom.length() / 2
            if (nPoints < 2) continue
            val lats = FloatArray(nPoints)
            val lons = FloatArray(nPoints)
            var minLat = Double.POSITIVE_INFINITY
            var maxLat = Double.NEGATIVE_INFINITY
            var minLon = Double.POSITIVE_INFINITY
            var maxLon = Double.NEGATIVE_INFINITY
            for (j in 0 until nPoints) {
                val lat = geom.getDouble(j * 2)
                val lon = geom.getDouble(j * 2 + 1)
                lats[j] = lat.toFloat()
                lons[j] = lon.toFloat()
                if (lat < minLat) minLat = lat
                if (lat > maxLat) maxLat = lat
                if (lon < minLon) minLon = lon
                if (lon > maxLon) maxLon = lon
            }
            out += Way(
                maxSpeedKmh = maxspeed,
                lats = lats,
                lons = lons,
                minLat = minLat.toFloat(),
                maxLat = maxLat.toFloat(),
                minLon = minLon.toFloat(),
                maxLon = maxLon.toFloat(),
            )
        }
        Timber.i("Loaded %d speed-limit ways from %s", out.size, ASSET_NAME)
        return out.toTypedArray()
    }

    // Immutable record per OSM way. Primitive arrays keep memory
    // overhead around (3 floats/point × 4 bytes) + bbox — roughly
    // 2 MB for the ~11 k Riyadh ways, parsed once at first use.
    internal data class Way(
        val maxSpeedKmh: Float,
        val lats: FloatArray,
        val lons: FloatArray,
        val minLat: Float,
        val maxLat: Float,
        val minLon: Float,
        val maxLon: Float,
    )

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

    internal companion object {
        const val ASSET_NAME = "riyadh_speed_limits.json"

        // Any way whose bounding box doesn't overlap a SEARCH_RADIUS_M
        // square around the user is skipped without computing segment
        // geometry. With rounded lat/lon at 5 decimals this is a
        // conservative bbox that never filters a candidate that would
        // otherwise score.
        const val SEARCH_RADIUS_M: Double = 40.0
        const val MAX_DIST_M: Double = 30.0
        const val BEARING_MIN_SPEED_MPS: Float = 3.0f
        const val BEARING_MAX_UNCERTAINTY_DEG: Float = 20.0f
        const val HEADING_FLOOR: Double = 0.2

        // ~1 m at the equator; at Riyadh's latitude lon-degrees are
        // smaller so the actual bbox check is tighter in longitude
        // than in latitude, which is fine — we never miss candidates,
        // only reject some that are already far.
        const val DEG_PER_METER_LAT: Double = 1.0 / 111_320.0
    }
}

// --- Scoring (pure, testable) -------------------------------------

// Iterate ways, score each candidate, return the best scoring way's
// maxspeed. Visible for tests — lets them inject a handful of ways
// directly instead of deserialising the full asset.
internal fun selectBestLimit(
    ways: Array<RoadSpeedLimitRepository.Way>,
    lat: Double,
    lon: Double,
    userBearingDeg: Float?,
): Float? {
    // Bounding-box pre-filter: grow the search square by MAX_DIST_M
    // on each side in lat degrees. Longitude scaling depends on
    // latitude, so we compute that once per query.
    val searchDegLat = RoadSpeedLimitRepository.MAX_DIST_M * RoadSpeedLimitRepository.DEG_PER_METER_LAT
    val metersPerDegLon = 111_320.0 * cos(Math.toRadians(lat))
    val searchDegLon = RoadSpeedLimitRepository.MAX_DIST_M / metersPerDegLon
    val latLo = lat - searchDegLat
    val latHi = lat + searchDegLat
    val lonLo = lon - searchDegLon
    val lonHi = lon + searchDegLon

    var bestScore = Double.NEGATIVE_INFINITY
    var bestLimit: Float? = null

    for (way in ways) {
        if (way.maxLat < latLo || way.minLat > latHi) continue
        if (way.maxLon < lonLo || way.minLon > lonHi) continue

        val scored = scoreWay(way, lat, lon, userBearingDeg)
        if (scored > bestScore) {
            bestScore = scored
            bestLimit = way.maxSpeedKmh
        }
    }
    return bestLimit
}

// 0..1 score for one candidate. Higher = more likely to be the road
// the user is actually on. Combines distanceScore * headingFactor,
// with a HEADING_FLOOR so a geometrically-closer road can still win
// if it bends momentarily away from the user's heading.
private fun scoreWay(
    way: RoadSpeedLimitRepository.Way,
    lat: Double,
    lon: Double,
    userBearingDeg: Float?,
): Double {
    var bestDist = Double.POSITIVE_INFINITY
    var bestSegBearing = 0.0
    val n = way.lats.size
    for (i in 0 until n - 1) {
        val d = distanceToSegmentMeters(
            lat, lon,
            way.lats[i].toDouble(), way.lons[i].toDouble(),
            way.lats[i + 1].toDouble(), way.lons[i + 1].toDouble(),
        )
        if (d < bestDist) {
            bestDist = d
            bestSegBearing = bearingDeg(
                way.lats[i].toDouble(), way.lons[i].toDouble(),
                way.lats[i + 1].toDouble(), way.lons[i + 1].toDouble(),
            )
        }
    }
    if (bestDist.isInfinite() || bestDist > RoadSpeedLimitRepository.MAX_DIST_M) {
        return Double.NEGATIVE_INFINITY
    }

    val distanceScore = max(0.0, 1.0 - bestDist / RoadSpeedLimitRepository.MAX_DIST_M)
    val headingFactor = if (userBearingDeg != null) {
        val diff = angularDiffDeg(userBearingDeg.toDouble(), bestSegBearing)
        val collapsed = if (diff > 90.0) 180.0 - diff else diff
        val headingScore = cos(Math.toRadians(collapsed)).coerceAtLeast(0.0)
        RoadSpeedLimitRepository.HEADING_FLOOR +
            (1.0 - RoadSpeedLimitRepository.HEADING_FLOOR) * headingScore
    } else {
        1.0
    }
    return distanceScore * headingFactor
}

// --- Geodesy helpers (shared with the other geometry paths) --------

// Shortest signed absolute difference between two bearings, 0..180°.
internal fun angularDiffDeg(a: Double, b: Double): Double {
    var d = ((a - b) % 360.0 + 360.0) % 360.0
    if (d > 180.0) d = 360.0 - d
    return d
}

// Initial bearing from (lat1,lon1) to (lat2,lon2), 0..360°. Fine for
// the short segments that make up OSM ways (< 1 km apart).
internal fun bearingDeg(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val phi1 = Math.toRadians(lat1)
    val phi2 = Math.toRadians(lat2)
    val dLon = Math.toRadians(lon2 - lon1)
    val y = sin(dLon) * cos(phi2)
    val x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(dLon)
    val theta = Math.toDegrees(atan2(y, x))
    return (theta + 360.0) % 360.0
}

// Great-circle distance, metres. Haversine within ±0.5% — plenty for
// matching a GPS fix to an OSM way.
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

// Perpendicular distance from point p to the line segment a..b, in
// metres. Equirectangular projection centred on p — correct to well
// under a metre for segments up to a few hundred metres at any
// latitude we care about.
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
