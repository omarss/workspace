package net.omarss.omono.location

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

// Shared Fused Location stream for UI-tier features that don't need
// the 1 Hz SpeedRepository cadence. The compass and the Places tab
// both consume this: compass so the heading / qibla / nearest-mosque
// bearings update live as the user moves, Places so the result list
// auto-refreshes when the user drives out of the fetched area.
//
// Kept separate from SpeedRepository because SpeedRepository starts
// and stops with the tracking feature (FeatureHostService). The
// compass + Places tabs need location regardless of whether speed
// tracking is active.
//
// Update cadence is deliberately slower than SpeedRepository's
// (3 s / 10 m min-update) — the UI consumers only need "we've moved
// enough for the bearing to shift", not every GPS tick.
@Singleton
class AppLocationStream @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    data class Fix(val latitude: Double, val longitude: Double)

    fun hasPermission(): Boolean =
        ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.ACCESS_FINE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission")
    fun updates(): Flow<Fix> = callbackFlow {
        if (!hasPermission()) {
            close(SecurityException("ACCESS_FINE_LOCATION not granted"))
            return@callbackFlow
        }
        val client = LocationServices.getFusedLocationProviderClient(context)
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, UPDATE_INTERVAL_MS)
            .setMinUpdateIntervalMillis(MIN_UPDATE_INTERVAL_MS)
            .setMinUpdateDistanceMeters(MIN_UPDATE_DISTANCE_M)
            .setWaitForAccurateLocation(false)
            .build()

        val callback = object : LocationCallback() {
            override fun onLocationResult(result: LocationResult) {
                val location = result.lastLocation ?: return
                trySend(Fix(location.latitude, location.longitude))
            }
        }

        runCatching {
            client.requestLocationUpdates(request, callback, Looper.getMainLooper())
        }.onFailure { Timber.w(it, "AppLocationStream: request failed") }

        // Seed with the last known fix so subscribers see a value
        // before the first real callback arrives — otherwise the
        // compass stays stuck on its initial "no location" state
        // for up to UPDATE_INTERVAL_MS.
        runCatching {
            client.lastLocation.addOnSuccessListener { loc ->
                if (loc != null) trySend(Fix(loc.latitude, loc.longitude))
            }
        }

        awaitClose {
            runCatching { client.removeLocationUpdates(callback) }
        }
    }

    private companion object {
        const val UPDATE_INTERVAL_MS: Long = 3_000L
        const val MIN_UPDATE_INTERVAL_MS: Long = 1_500L
        // Ignore updates smaller than this — a phone on a desk drifts
        // within its GPS accuracy window forever; filtering kills the
        // fake "movement" that would keep firing re-fetches.
        const val MIN_UPDATE_DISTANCE_M: Float = 5f
    }
}
