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

// Resolves "which road am I on, and what's its speed limit?" for the
// current GPS fix. Tries the self-hosted `/v1/roads` API first
// (OSM-backed, returns both the speed limit AND the road's name in
// English + Arabic). On network failure, HTTP error, or missing
// credentials, falls back to the bundled OpenStreetMap extract under
// `assets/riyadh_speed_limits.json`, which covers the same dataset
// for speed-limit-only queries.
//
// Results are cached by position: a re-query within CACHE_RADIUS_M
// and CACHE_TTL_MS of the last call returns the cached value
// synchronously, so the typical 1 Hz GPS cadence produces about one
// network hit per 5 s / 100 m of driving.
//
// Bundled-asset selection: within SEARCH_RADIUS_M of the position,
// candidate ways are scored by distance-to-nearest-segment and, when
// the user's heading is trustworthy, by how closely that segment's
// bearing aligns with the direction of travel. Bearings are collapsed
// mod 180° so bidirectional roads are treated symmetrically.
@Singleton
class RoadSpeedLimitRepository @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val roadsClient: RoadsClient,
) {

    private val mutex = Mutex()
    @Volatile private var ways: Array<Way>? = null

    // Last-seen road info + where/when we saw it. Used as a small
    // rolling cache so every location tick isn't a fresh HTTP call.
    @Volatile private var cached: CachedRoad? = null

    // Full road info (speed limit + name) for the current fix. Prefers
    // the live API; if it can't be reached, falls back to the bundled
    // asset for speed only.
    suspend fun roadAt(
        lat: Double,
        lon: Double,
        bearingDeg: Float? = null,
        bearingAccuracyDeg: Float? = null,
        speedMps: Float = 0f,
    ): RoadInfo {
        cachedIfFresh(lat, lon)?.let { return it.info }

        val useBearing = isBearingTrustworthy(bearingDeg, bearingAccuracyDeg, speedMps)
        val apiCandidates = roadsClient.roadsAt(lat, lon)
        if (apiCandidates != null) {
            // Network succeeded (even if the list is empty — point was
            // simply outside every polygon). Pick the best candidate;
            // cache regardless so repeated off-road fixes don't hammer
            // the endpoint every tick.
            val best = pickBestCandidate(apiCandidates, if (useBearing) bearingDeg else null)
            val info = best?.toRoadInfo() ?: RoadInfo.EMPTY
            cached = CachedRoad(lat, lon, System.currentTimeMillis(), info)
            return info
        }

        // Network unreachable — fall back to the offline speed-limit
        // asset. Name stays null (no offline name source yet).
        val loaded = ensureLoaded()
        val offlineLimit = loaded?.let {
            selectBestLimit(
                ways = it,
                lat = lat,
                lon = lon,
                userBearingDeg = if (useBearing) bearingDeg else null,
            )
        }
        val info = RoadInfo(
            maxspeedKmh = offlineLimit,
            name = null,
            nameEn = null,
            highway = null,
        )
        cached = CachedRoad(lat, lon, System.currentTimeMillis(), info)
        return info
    }

    // Thin compatibility shim. SpeedFeature's existing call sites
    // continue to read just the limit; the name side channel is read
    // separately via roadAt().
    suspend fun limitKmh(
        lat: Double,
        lon: Double,
        bearingDeg: Float? = null,
        bearingAccuracyDeg: Float? = null,
        speedMps: Float = 0f,
    ): Float? = roadAt(lat, lon, bearingDeg, bearingAccuracyDeg, speedMps).maxspeedKmh

    private fun cachedIfFresh(lat: Double, lon: Double): CachedRoad? {
        val c = cached ?: return null
        val now = System.currentTimeMillis()
        if (now - c.timestampMs > CACHE_TTL_MS) return null
        val distance = haversineMeters(c.lat, c.lon, lat, lon)
        if (distance > CACHE_RADIUS_M) return null
        return c
    }

    private fun pickBestCandidate(
        candidates: List<RoadCandidate>,
        userBearingDeg: Float?,
    ): RoadCandidate? {
        if (candidates.isEmpty()) return null
        if (userBearingDeg == null || candidates.size == 1) return candidates[0]
        // Server orders by highway class then area; for divided
        // highways that means the top pick might be the opposite
        // carriageway. Use bearing alignment to break ties — collapse
        // mod 180° so a two-way road is symmetric.
        return candidates.minByOrNull { c ->
            val segBearing = c.headingDeg?.toDouble() ?: return@minByOrNull Double.POSITIVE_INFINITY
            val diff = angularDiffDeg(userBearingDeg.toDouble(), segBearing)
            if (diff > 90.0) 180.0 - diff else diff
        } ?: candidates[0]
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

        // API response cache. Per FEEDBACK.md §6, the server suggests
        // re-querying on ≥100 m movement OR when the point leaves the
        // cached polygon. Without the polygon locally we use a more
        // conservative distance threshold and a short TTL so stale
        // limits clear automatically on slow drives.
        const val CACHE_RADIUS_M: Double = 80.0
        const val CACHE_TTL_MS: Long = 5_000L
    }
}

// Everything the UI needs to know about the road the user is currently
// on. Preserves null-ness at the source fields — consumers should
// decide between Arabic / English, not the repository.
data class RoadInfo(
    val maxspeedKmh: Float?,
    val name: String?,
    val nameEn: String?,
    val highway: String?,
) {
    companion object {
        val EMPTY = RoadInfo(null, null, null, null)
    }
}

private data class CachedRoad(
    val lat: Double,
    val lon: Double,
    val timestampMs: Long,
    val info: RoadInfo,
)

private fun RoadCandidate.toRoadInfo(): RoadInfo = RoadInfo(
    maxspeedKmh = maxspeedKmh?.toFloat(),
    name = name,
    nameEn = nameEn,
    highway = highway,
)

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
