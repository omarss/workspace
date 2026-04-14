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

// Wraps FusedLocationProviderClient as a cold Flow of speed in m/s.
// The underlying callback is registered on Looper.getMainLooper() because
// FusedLocationProvider posts to whichever Looper you give it; main is
// the safest choice for a service callback.
@Singleton
class SpeedRepository @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {
    private val client by lazy { LocationServices.getFusedLocationProviderClient(context) }

    @SuppressLint("MissingPermission")
    fun speedMetersPerSecond(): Flow<Float> = callbackFlow {
        if (!hasLocationPermission()) {
            close(SecurityException("ACCESS_FINE_LOCATION not granted"))
            return@callbackFlow
        }

        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, UPDATE_INTERVAL_MS)
            .setMinUpdateIntervalMillis(MIN_UPDATE_INTERVAL_MS)
            .setWaitForAccurateLocation(false)
            .build()

        val callback = object : LocationCallback() {
            override fun onLocationResult(result: LocationResult) {
                val location = result.lastLocation ?: return
                if (!location.hasSpeed()) return
                trySend(location.speed)
            }
        }

        Timber.d("Requesting location updates @ %dms", UPDATE_INTERVAL_MS)
        client.requestLocationUpdates(request, callback, Looper.getMainLooper())

        awaitClose {
            Timber.d("Removing location updates")
            client.removeLocationUpdates(callback)
        }
    }

    private fun hasLocationPermission(): Boolean =
        ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.ACCESS_FINE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED

    private companion object {
        const val UPDATE_INTERVAL_MS: Long = 1_000L
        const val MIN_UPDATE_INTERVAL_MS: Long = 500L
    }
}
