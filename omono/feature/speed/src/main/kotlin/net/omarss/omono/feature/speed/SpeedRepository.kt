package net.omarss.omono.feature.speed

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.os.Looper
import androidx.core.content.ContextCompat
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

// Single GPS sample. Emitted by SpeedRepository.locations() at adaptive
// rate (see ADAPTIVE constants below). Speed is in m/s, lat/lon in WGS84,
// bearing in degrees clockwise from true north (null when FusedLocation
// can't infer direction of travel — typically while stationary).
//
// `speedMps` is post-filtered: GPS ghosts at rest (which can report
// 30 m/s while parked under an overpass) are clamped to 0 inside the
// repository so every downstream consumer — notification, trip
// recorder, traffic watcher — sees a clean signal. The raw reading
// is kept around as `rawSpeedMps` for diagnostics but never surfaced
// in the UI directly.
data class LocationSnapshot(
    val latitude: Double,
    val longitude: Double,
    val speedMps: Float,
    val accuracyMeters: Float,
    val bearingDeg: Float? = null,
    val bearingAccuracyDeg: Float? = null,
    val speedAccuracyMps: Float? = null,
    val rawSpeedMps: Float = speedMps,
)

// Filter decision — pure and unit-testable. Returns the speed we want
// to show the user, which is `rawSpeed` when the GPS fix passes every
// quality gate and 0 otherwise. Logic:
//
//  * hasSpeed must be true. Some fixes (e.g. cell-tower fallback) have
//    no speed at all — they should read as stationary, not garbage.
//  * If the provider told us how confident it is in the speed reading
//    (API 26+), require `speedAccuracy` ≤ SPEED_ACCURACY_MAX_MPS. This
//    is the single most reliable filter — a 120 km/h ghost will come
//    with a ±15 m/s uncertainty that pass-through code ignores.
//  * If we only have position accuracy, require ≤ POSITION_ACCURACY_MAX_M
//    AND that the reported speed is above a very small positive floor.
//    A flat 0 m/s reading with any accuracy is always trusted (the
//    provider is correctly saying "stationary"), but a non-zero speed
//    paired with a 50 m accuracy halo is GPS jitter we'd rather drop.
internal fun filterSpeed(
    hasSpeed: Boolean,
    rawSpeedMps: Float,
    hasAccuracy: Boolean,
    accuracyMeters: Float,
    hasSpeedAccuracy: Boolean,
    speedAccuracyMps: Float,
): Float {
    if (!hasSpeed) return 0f
    if (rawSpeedMps <= 0f) return 0f
    if (hasSpeedAccuracy) {
        return if (speedAccuracyMps <= SPEED_ACCURACY_MAX_MPS) rawSpeedMps else 0f
    }
    if (!hasAccuracy || accuracyMeters > POSITION_ACCURACY_MAX_M) return 0f
    return rawSpeedMps
}

// Filter thresholds live at file scope so the test can exercise
// boundary behaviour against the same constants the production path
// uses — no magic-number drift between the two.
internal const val SPEED_ACCURACY_MAX_MPS: Float = 2.0f
internal const val POSITION_ACCURACY_MAX_M: Float = 20.0f

// Wraps FusedLocationProviderClient as a cold Flow of LocationSnapshot.
//
// Adaptive GPS: the callback self-observes its own speed samples. When a
// sample reports movement above MOVING_THRESHOLD_MPS, the "active" timer
// resets. When no movement has been seen for IDLE_TIMEOUT_MS the callback
// is silently reinstalled at SLOW_INTERVAL_MS; the next real movement
// promotes it back to FAST_INTERVAL_MS. Net effect: the GPS radio burns
// ~10x less battery while you're parked, with zero API-level contracts
// (no ActivityRecognition permission, no Play Services workers).
//
// Callback posts to the main looper because FusedLocationProvider dispatches
// on whichever Looper it's handed, and main is the safest choice for a
// long-lived foreground service callback.
@Singleton
class SpeedRepository @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {
    private val client by lazy { LocationServices.getFusedLocationProviderClient(context) }

    @SuppressLint("MissingPermission")
    fun locations(): Flow<LocationSnapshot> = callbackFlow {
        if (!hasLocationPermission()) {
            close(SecurityException("ACCESS_FINE_LOCATION not granted"))
            return@callbackFlow
        }

        // Mutable state captured by the installed callback. Wrapped in
        // single-element arrays so the inner lambdas can mutate them
        // without Kotlin promoting them to AtomicReferences.
        val currentIntervalMs = longArrayOf(FAST_INTERVAL_MS)
        val lastMoveAtMs = longArrayOf(System.currentTimeMillis())
        val installedCallback = arrayOfNulls<LocationCallback>(1)

        fun install(intervalMs: Long) {
            installedCallback[0]?.let { client.removeLocationUpdates(it) }
            val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, intervalMs)
                .setMinUpdateIntervalMillis(intervalMs / 2)
                .setWaitForAccurateLocation(false)
                .build()

            val cb = object : LocationCallback() {
                override fun onLocationResult(result: LocationResult) {
                    val location = result.lastLocation ?: return
                    val rawSpeed = if (location.hasSpeed()) location.speed else 0f
                    val trustedSpeed = filterSpeed(
                        hasSpeed = location.hasSpeed(),
                        rawSpeedMps = rawSpeed,
                        hasAccuracy = location.hasAccuracy(),
                        accuracyMeters = location.accuracy,
                        hasSpeedAccuracy = location.hasSpeedAccuracy(),
                        speedAccuracyMps = location.speedAccuracyMetersPerSecond,
                    )
                    val snapshot = LocationSnapshot(
                        latitude = location.latitude,
                        longitude = location.longitude,
                        speedMps = trustedSpeed,
                        accuracyMeters = if (location.hasAccuracy()) location.accuracy else Float.NaN,
                        bearingDeg = if (location.hasBearing()) location.bearing else null,
                        // bearingAccuracyDegrees added in API 26 — minSdk 26.
                        bearingAccuracyDeg =
                            if (location.hasBearingAccuracy()) location.bearingAccuracyDegrees else null,
                        speedAccuracyMps =
                            if (location.hasSpeedAccuracy()) location.speedAccuracyMetersPerSecond else null,
                        rawSpeedMps = rawSpeed,
                    )
                    trySend(snapshot)

                    val now = System.currentTimeMillis()
                    if (snapshot.speedMps >= MOVING_THRESHOLD_MPS) {
                        lastMoveAtMs[0] = now
                    }
                    val idleForMs = now - lastMoveAtMs[0]
                    val desired = if (idleForMs > IDLE_TIMEOUT_MS) {
                        SLOW_INTERVAL_MS
                    } else {
                        FAST_INTERVAL_MS
                    }
                    if (desired != currentIntervalMs[0]) {
                        Timber.d(
                            "Adaptive GPS: %dms → %dms",
                            currentIntervalMs[0],
                            desired,
                        )
                        currentIntervalMs[0] = desired
                        install(desired)
                    }
                }
            }
            installedCallback[0] = cb
            currentIntervalMs[0] = intervalMs
            client.requestLocationUpdates(request, cb, Looper.getMainLooper())
            Timber.d("Requesting location updates @ %dms", intervalMs)
        }

        install(FAST_INTERVAL_MS)

        awaitClose {
            installedCallback[0]?.let {
                Timber.d("Removing location updates")
                client.removeLocationUpdates(it)
            }
        }
    }

    private fun hasLocationPermission(): Boolean =
        ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.ACCESS_FINE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED

    private companion object {
        const val FAST_INTERVAL_MS: Long = 1_000L
        const val SLOW_INTERVAL_MS: Long = 10_000L

        // Speed threshold that resets the "moving" timer. 0.5 m/s ≈ a
        // slow walking pace — well below noise floor for a car.
        const val MOVING_THRESHOLD_MPS: Float = 0.5f

        // No movement for this long → drop to slow mode. First real
        // sample above the threshold promotes us back immediately.
        const val IDLE_TIMEOUT_MS: Long = 60_000L
    }
}
