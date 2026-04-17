package net.omarss.omono.feature.speed

import javax.inject.Inject
import javax.inject.Singleton
import kotlin.math.asin
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.sin

// Polls a live-traffic source for the point ~500 m ahead of the user
// and returns a Warning when that stretch of road is significantly
// slower than its free-flow speed, so the user has a chance to pick an
// alternate route before committing to the jam.
//
// Behaviour gates:
//  * Only polls while actually driving (speedMps ≥ MIN_DRIVING_MPS) and
//    with a trustworthy bearing — otherwise "ahead" has no meaning.
//  * At most one poll per POLL_INTERVAL_MS so a long drive stays well
//    under the TomTom free-tier daily cap, even sharing the key with
//    the places client.
//  * Warnings are deduped by a ~100 m grid cell around the look-ahead
//    point for DEDUPE_WINDOW_MS, so crawling into the same jam doesn't
//    beep every 30 s.
@Singleton
class TrafficAheadWatcher @Inject constructor(
    private val source: TrafficFlowSource,
) {

    data class Warning(
        val currentKmh: Float,
        val freeFlowKmh: Float,
        val roadClosure: Boolean,
        val distanceMeters: Float,
    )

    // Nullable so a fresh watcher doesn't treat "now" as only moments
    // after an imaginary last poll — the very first call must be
    // allowed through the throttle gate.
    private var lastPollMs: Long? = null
    private var lastWarnCell: String? = null
    private var lastWarnAtMs: Long = 0L

    // Feed every GPS sample in; the watcher decides whether to poll.
    // Returns a Warning only on the transition into a congestion zone
    // (subject to dedupe) so the caller can play a single alert tone.
    suspend fun onLocation(
        snapshot: LocationSnapshot,
        nowMs: Long = System.currentTimeMillis(),
    ): Warning? {
        if (snapshot.speedMps < MIN_DRIVING_MPS) return null
        val bearing = snapshot.bearingDeg ?: return null
        val bearingUncertainty = snapshot.bearingAccuracyDeg ?: Float.MAX_VALUE
        if (bearingUncertainty > MAX_BEARING_UNCERTAINTY_DEG) return null
        val previousPoll = lastPollMs
        if (previousPoll != null && nowMs - previousPoll < POLL_INTERVAL_MS) return null

        lastPollMs = nowMs
        val (aheadLat, aheadLon) = projectAhead(
            snapshot.latitude, snapshot.longitude, bearing.toDouble(), LOOKAHEAD_M,
        )
        val sample = source.sample(aheadLat, aheadLon) ?: return null

        val ratio = if (sample.freeFlowSpeedKmh > 0f) {
            sample.currentSpeedKmh / sample.freeFlowSpeedKmh
        } else {
            1f
        }
        val jammed = sample.roadClosure ||
            (ratio < BAD_RATIO && sample.confidence >= MIN_CONFIDENCE)
        if (!jammed) return null

        val cell = gridCell(aheadLat, aheadLon)
        if (cell == lastWarnCell && (nowMs - lastWarnAtMs) < DEDUPE_WINDOW_MS) {
            return null
        }
        lastWarnCell = cell
        lastWarnAtMs = nowMs

        return Warning(
            currentKmh = sample.currentSpeedKmh,
            freeFlowKmh = sample.freeFlowSpeedKmh,
            roadClosure = sample.roadClosure,
            distanceMeters = LOOKAHEAD_M,
        )
    }

    private companion object {
        const val MIN_DRIVING_MPS: Float = 5f        // ~18 km/h — unambiguously in-vehicle
        const val MAX_BEARING_UNCERTAINTY_DEG: Float = 25f
        const val POLL_INTERVAL_MS: Long = 30_000L
        const val LOOKAHEAD_M: Float = 500f
        const val BAD_RATIO: Float = 0.5f            // current < half of free-flow → jam
        const val MIN_CONFIDENCE: Float = 0.7f
        const val DEDUPE_WINDOW_MS: Long = 5 * 60_000L
        const val GRID_CELL_DEG: Double = 0.001      // ~111 m at the equator, a bit tighter at ϕ=24°
    }

    // Grid cell id used only for dedupe equality — the exact dimension
    // isn't load-bearing, just needs to collapse adjacent look-ahead
    // points into the same bucket.
    private fun gridCell(lat: Double, lon: Double): String =
        "${floor(lat / GRID_CELL_DEG).toLong()}:${floor(lon / GRID_CELL_DEG).toLong()}"
}

// Projects (lat,lon) a fixed distance in the direction of `bearingDeg`
// along the great circle. Accurate to the metre for the short
// look-ahead distances we use; the simpler equirectangular projection
// distorts near the poles and at high latitudes.
internal fun projectAhead(
    lat: Double,
    lon: Double,
    bearingDeg: Double,
    distanceMeters: Float,
): Pair<Double, Double> {
    val r = 6_371_000.0
    val delta = distanceMeters / r
    val theta = Math.toRadians(bearingDeg)
    val phi1 = Math.toRadians(lat)
    val lambda1 = Math.toRadians(lon)

    val phi2 = asin(sin(phi1) * cos(delta) + cos(phi1) * sin(delta) * cos(theta))
    val lambda2 = lambda1 + atan2(
        sin(theta) * sin(delta) * cos(phi1),
        cos(delta) - sin(phi1) * sin(phi2),
    )
    return Math.toDegrees(phi2) to ((Math.toDegrees(lambda2) + 540.0) % 360.0 - 180.0)
}
