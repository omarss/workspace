package net.omarss.omono.feature.speed.trips

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import net.omarss.omono.feature.speed.LocationSnapshot
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

// Accumulates GPS samples into the current trip and persists to Room
// when the user stops tracking or the trip goes idle for more than
// IDLE_FINALIZE_MS of no significant movement.
//
// A trip starts on the first sample whose speed exceeds MOVE_THRESHOLD
// (so we don't record a "trip" of you sitting in your parked car while
// the foreground service is running). Trips shorter than MIN_DISTANCE_M
// are discarded — a few GPS wobbles are not a trip.
@Singleton
class TripRecorder @Inject constructor(
    private val dao: TripDao,
) {
    // Long-lived IO scope for the DB writes. SupervisorJob means a
    // single failed insert doesn't cancel the recorder.
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    // Both onLocation and finalizeCurrent mutate `current`. They're
    // invoked from different threads (onLocation runs on whatever
    // dispatcher collects the location Flow; finalizeCurrent is called
    // from SpeedFeature.stop() on the caller's thread). Without this
    // lock a stop racing with an in-flight sample can double-finalize
    // or drop the trip entirely.
    private val lock = Any()
    private var current: TripBuilder? = null

    fun onLocation(snapshot: LocationSnapshot, nowMs: Long = System.currentTimeMillis()) {
        synchronized(lock) {
            val trip = current
            if (trip == null) {
                if (snapshot.speedMps >= MOVE_THRESHOLD_MPS) {
                    current = TripBuilder(startAtMs = nowMs).also { it.record(snapshot, nowMs) }
                    Timber.d("Trip started")
                }
                return
            }

            trip.record(snapshot, nowMs)

            // Auto-finalize if stationary too long.
            if (nowMs - trip.lastMoveAtMs > IDLE_FINALIZE_MS) {
                finalizeCurrentLocked("idle timeout")
            }
        }
    }

    // Called by SpeedFeature.stop() so the trip is saved when the user
    // manually stops tracking, not just on idle timeout.
    fun finalizeCurrent(reason: String = "manual stop") {
        synchronized(lock) { finalizeCurrentLocked(reason) }
    }

    // Must be called with `lock` held.
    private fun finalizeCurrentLocked(reason: String) {
        val trip = current ?: return
        current = null
        if (trip.distanceMeters < MIN_DISTANCE_M) {
            Timber.d("Discarding short trip (%.1fm, reason=%s)", trip.distanceMeters, reason)
            return
        }
        val entity = trip.build()
        Timber.i(
            "Trip finalized (%s): %.0fm, max %.1f km/h, %.1f min",
            reason,
            entity.distanceMeters,
            entity.maxSpeedKmh,
            (entity.endAtMillis - entity.startAtMillis) / 60_000.0,
        )
        scope.launch {
            runCatching { dao.insert(entity) }
                .onFailure { Timber.w(it, "Failed to persist trip") }
        }
    }

    private companion object {
        const val MOVE_THRESHOLD_MPS: Float = 0.5f
        const val IDLE_FINALIZE_MS: Long = 3 * 60 * 1000L // 3 minutes stationary → trip over
        const val MIN_DISTANCE_M: Double = 50.0
        const val TELEPORT_REJECT_M: Double = 500.0
    }
}

internal class TripBuilder(val startAtMs: Long) {
    var distanceMeters: Double = 0.0
    var maxSpeedKmh: Float = 0f
    var speedSumKmh: Double = 0.0
    var speedSamples: Int = 0
    var lastMoveAtMs: Long = startAtMs

    private var lastLat: Double? = null
    private var lastLon: Double? = null

    fun record(snap: LocationSnapshot, nowMs: Long) {
        val prevLat = lastLat
        val prevLon = lastLon
        if (prevLat != null && prevLon != null) {
            val d = haversineMeters(prevLat, prevLon, snap.latitude, snap.longitude)
            // Reject obvious GPS teleports (>500m between samples is
            // almost always a reacquisition artifact, not real motion).
            if (d < TELEPORT_REJECT_M) {
                distanceMeters += d
            }
        }
        lastLat = snap.latitude
        lastLon = snap.longitude

        val speedKmh = snap.speedMps * 3.6f
        if (speedKmh > maxSpeedKmh) maxSpeedKmh = speedKmh
        speedSumKmh += speedKmh
        speedSamples += 1

        if (snap.speedMps >= MOVE_THRESHOLD_MPS) {
            lastMoveAtMs = nowMs
        }
    }

    fun build(endAtMs: Long = lastMoveAtMs): TripEntity = TripEntity(
        startAtMillis = startAtMs,
        endAtMillis = endAtMs,
        distanceMeters = distanceMeters,
        maxSpeedKmh = maxSpeedKmh,
        avgSpeedKmh = if (speedSamples > 0) (speedSumKmh / speedSamples).toFloat() else 0f,
    )

    private companion object {
        const val MOVE_THRESHOLD_MPS: Float = 0.5f
        const val TELEPORT_REJECT_M: Double = 500.0
    }
}

// Haversine formula for great-circle distance on a sphere the size of
// Earth. Accurate enough for < 1 km segments; we don't care about
// centimetres in a consumer trip tracker.
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
