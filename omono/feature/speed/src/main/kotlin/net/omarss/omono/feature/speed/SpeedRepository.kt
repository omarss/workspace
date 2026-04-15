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
// rate (see ADAPTIVE constants below). Speed is in m/s, lat/lon in WGS84.
data class LocationSnapshot(
    val latitude: Double,
    val longitude: Double,
    val speedMps: Float,
    val accuracyMeters: Float,
)

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
                    val snapshot = LocationSnapshot(
                        latitude = location.latitude,
                        longitude = location.longitude,
                        speedMps = if (location.hasSpeed()) location.speed else 0f,
                        accuracyMeters = if (location.hasAccuracy()) location.accuracy else Float.NaN,
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
