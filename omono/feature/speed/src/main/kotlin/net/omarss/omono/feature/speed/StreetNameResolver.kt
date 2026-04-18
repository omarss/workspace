package net.omarss.omono.feature.speed

import android.content.Context
import android.location.Address
import android.location.Geocoder
import android.os.Build
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import timber.log.Timber
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

// Reverse-geocodes GPS samples into a human-readable street / road
// name for the Tracking hero. Rate-limited in two dimensions so a
// typical drive results in single-digit lookups per minute:
//
//   * Temporal: at most one geocode per RESOLVE_COOLDOWN_MS.
//   * Spatial:  only geocode once the device has moved MIN_MOVE_M
//     since the last successful resolve — running circles around a
//     parking lot doesn't burn lookups.
//
// Android's Geocoder is a thin wrapper around the device's configured
// geocoder backend (usually Google's). On API 33+ it offers a
// callback-based `getFromLocation(..., listener)`; on older APIs the
// only call available is the deprecated synchronous variant, which we
// run on Dispatchers.IO so the main thread never waits on network.
//
// When the geocoder isn't present (rare but possible on custom ROMs)
// or a lookup fails, `street` simply stays on its last good value —
// the hero shows stale-but-useful rather than flickering.
@Singleton
class StreetNameResolver @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val _street = MutableStateFlow<String?>(null)
    val street: StateFlow<String?> = _street.asStateFlow()

    private val geocoder: Geocoder? by lazy {
        if (Geocoder.isPresent()) Geocoder(context, Locale.getDefault()) else null
    }

    @Volatile private var lastLat: Double? = null
    @Volatile private var lastLng: Double? = null
    @Volatile private var lastResolveMs: Long = 0L

    // Feed every GPS sample in. The resolver decides per-sample whether
    // to actually kick off a geocode; cheap to call at the native 1 Hz
    // GPS cadence.
    fun onLocation(snapshot: LocationSnapshot) {
        val now = System.currentTimeMillis()
        if (now - lastResolveMs < RESOLVE_COOLDOWN_MS) return
        val prevLat = lastLat
        val prevLng = lastLng
        if (prevLat != null && prevLng != null) {
            val moved = distanceMeters(prevLat, prevLng, snapshot.latitude, snapshot.longitude)
            if (moved < MIN_MOVE_M) return
        }
        lastResolveMs = now
        lastLat = snapshot.latitude
        lastLng = snapshot.longitude
        scope.launch { resolve(snapshot.latitude, snapshot.longitude) }
    }

    fun reset() {
        _street.value = null
        lastLat = null
        lastLng = null
        lastResolveMs = 0L
    }

    private suspend fun resolve(lat: Double, lng: Double) {
        val geocoder = geocoder ?: return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            // Native async API — the callback fires on an arbitrary
            // thread; just drop the result on the StateFlow.
            runCatching {
                geocoder.getFromLocation(lat, lng, 1) { addresses ->
                    _street.value = extractStreet(addresses.firstOrNull())
                }
            }.onFailure { Timber.w(it, "Geocoder async failed") }
        } else {
            @Suppress("DEPRECATION")
            runCatching {
                val results = geocoder.getFromLocation(lat, lng, 1)
                _street.value = extractStreet(results?.firstOrNull())
            }.onFailure { Timber.w(it, "Geocoder sync failed") }
        }
    }

    // Prefer a street name (Thoroughfare); fall back to neighbourhood
    // (SubLocality) and then city (Locality). featureName is what
    // Geocoder exposes for unnamed highways and is preferred over the
    // neighbourhood on highway driving.
    private fun extractStreet(addr: Address?): String? {
        if (addr == null) return null
        val thoroughfare = addr.thoroughfare?.takeIf { it.isNotBlank() }
        val featureName = addr.featureName?.takeIf { it.isNotBlank() && it != thoroughfare }
        val subLocality = addr.subLocality?.takeIf { it.isNotBlank() }
        val locality = addr.locality?.takeIf { it.isNotBlank() }
        return thoroughfare ?: featureName ?: subLocality ?: locality
    }

    private companion object {
        const val RESOLVE_COOLDOWN_MS = 10_000L
        const val MIN_MOVE_M = 40.0
    }
}

// Haversine distance in metres. Good enough for the "have we moved
// 40 m yet?" check — no need for an ellipsoid model at this scale.
private fun distanceMeters(lat1: Double, lng1: Double, lat2: Double, lng2: Double): Double {
    val earthRadius = 6_371_000.0
    val dLat = Math.toRadians(lat2 - lat1)
    val dLng = Math.toRadians(lng2 - lng1)
    val a = kotlin.math.sin(dLat / 2).let { it * it } +
        kotlin.math.cos(Math.toRadians(lat1)) *
        kotlin.math.cos(Math.toRadians(lat2)) *
        kotlin.math.sin(dLng / 2).let { it * it }
    val c = 2 * kotlin.math.atan2(kotlin.math.sqrt(a), kotlin.math.sqrt(1 - a))
    return earthRadius * c
}
