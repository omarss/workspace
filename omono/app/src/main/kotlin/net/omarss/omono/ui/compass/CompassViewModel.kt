package net.omarss.omono.ui.compass

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import net.omarss.omono.feature.places.HeadingSensor
import net.omarss.omono.location.AppLocationStream
import timber.log.Timber
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt
import javax.inject.Inject

// Dedicated compass tab. Subscribes to two live streams:
//   - the magnetometer (HeadingSensor), at sensor rate, and
//   - the fused location stream (AppLocationStream), at ~3 s / 5 m.
//
// The qibla and nearest-mosque bearings are derived reactively from
// whatever the latest fix is, so both arrows stay pointed correctly
// as the user walks or drives. Nearest-mosque identity is only
// re-queried against the offline directory when the user has moved
// far enough for the answer to plausibly change (MOSQUE_REFRESH_M).
@HiltViewModel
class CompassViewModel @Inject constructor(
    headingSensor: HeadingSensor,
    private val locationStream: AppLocationStream,
    private val mosqueDirectory: MosqueDirectory,
) : ViewModel() {

    private val heading: StateFlow<Float> = headingSensor.headings()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), initialValue = 0f)

    // Live GPS fix. `null` until the first callback lands (or until
    // the user grants location permission).
    private val fix: StateFlow<AppLocationStream.Fix?> = locationStream.updates()
        .catch { err ->
            Timber.w(err, "AppLocationStream failed")
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), initialValue = null)

    // Mosque identity (lat/lon/name) — re-queried on sparse triggers
    // so we don't hammer the on-disk asset on every 5 m update. The
    // *bearing* to it is derived live in the combine below from the
    // current fix, so driving past the mosque flips the arrow
    // instantly regardless of how long ago we re-identified it.
    private val mosqueIdentity = MutableStateFlow<MosqueSnapshot?>(null)
    @Volatile private var lastMosqueLookupFix: AppLocationStream.Fix? = null

    val uiState: StateFlow<CompassUiState> = combine(
        heading,
        fix,
        mosqueIdentity,
    ) { h, f, mosque ->
        val qibla = f?.let { qiblaBearingDeg(it.latitude, it.longitude).toFloat() }
        val mosqueBearing = if (f != null && mosque != null) {
            bearingDeg(f.latitude, f.longitude, mosque.latitude, mosque.longitude).toFloat()
        } else null
        val mosqueDistance = if (f != null && mosque != null) {
            haversineMeters(f.latitude, f.longitude, mosque.latitude, mosque.longitude)
        } else null
        CompassUiState(
            headingDeg = h,
            location = f?.let { it.latitude to it.longitude },
            qiblaBearingDeg = qibla,
            nearestMosque = if (mosque != null && mosqueBearing != null && mosqueDistance != null) {
                MosqueDirectory.NearestResult(
                    name = mosque.name,
                    latitude = mosque.latitude,
                    longitude = mosque.longitude,
                    distanceMeters = mosqueDistance,
                    bearingDeg = mosqueBearing,
                )
            } else null,
            errorMessage = if (!locationStream.hasPermission() && f == null) {
                "Location permission needed"
            } else null,
            locationAvailable = f != null,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = CompassUiState(),
    )

    init {
        // Re-identify the nearest mosque whenever the user moves at
        // least MOSQUE_REFRESH_M since the last lookup. distinct-
        // UntilChanged on the grid bucket keeps the launch rate sane.
        fix
            .map { it?.toGridBucket() }
            .distinctUntilChanged()
            .onEach { refreshMosqueIfNeeded() }
            .launchIn(viewModelScope)
    }

    private suspend fun refreshMosqueIfNeeded() {
        val current = fix.value ?: return
        val last = lastMosqueLookupFix
        if (last != null) {
            val moved = haversineMeters(
                last.latitude, last.longitude,
                current.latitude, current.longitude,
            )
            if (moved < MOSQUE_REFRESH_M && mosqueIdentity.value != null) return
        }
        lastMosqueLookupFix = current
        val result = runCatching {
            mosqueDirectory.nearestTo(current.latitude, current.longitude)
        }.onFailure { Timber.w(it, "MosqueDirectory lookup failed") }
            .getOrNull()
        mosqueIdentity.value = result?.let {
            MosqueSnapshot(name = it.name, latitude = it.latitude, longitude = it.longitude)
        }
    }

    private fun AppLocationStream.Fix.toGridBucket(): Pair<Int, Int> =
        // ~30 m grid. One ping per 30 m of movement kicks the
        // re-identification check above; MOSQUE_REFRESH_M decides
        // whether that check actually fires a lookup.
        (latitude * 3_000.0).toInt() to (longitude * 3_000.0).toInt()

    private data class MosqueSnapshot(
        val name: String?,
        val latitude: Double,
        val longitude: Double,
    )

    // Exposed as a no-op for the refresh button — the stream keeps
    // itself fresh, so the button's job is purely reassurance.
    fun refresh() {
        viewModelScope.launch { refreshMosqueIfNeeded() }
    }

    private companion object {
        // Re-identify the nearest mosque once the user's moved this
        // far. Smaller = more lookups, bigger = a stale identity if
        // the user passes a closer mosque. 50 m is tight enough that
        // driving past one mosque flips the arrow to the next before
        // you've gone a block; the on-disk lookup is ~1 ms so extra
        // calls are cheap. Combined with the 30 m grid-bucket debounce
        // above, a stationary phone won't thrash the asset on GPS
        // wander near a bucket boundary.
        const val MOSQUE_REFRESH_M = 50.0
    }
}

// Haversine + initial bearing. Local copies so this VM doesn't reach
// into feature/speed's internals.
private fun haversineMeters(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val r = 6_371_000.0
    val dLat = Math.toRadians(lat2 - lat1)
    val dLon = Math.toRadians(lon2 - lon1)
    val a = sin(dLat / 2).let { it * it } +
        cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) *
        sin(dLon / 2).let { it * it }
    val c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return r * c
}

private fun bearingDeg(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val phi1 = Math.toRadians(lat1)
    val phi2 = Math.toRadians(lat2)
    val dLon = Math.toRadians(lon2 - lon1)
    val y = sin(dLon) * cos(phi2)
    val x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(dLon)
    return (Math.toDegrees(atan2(y, x)) + 360.0) % 360.0
}

data class CompassUiState(
    val headingDeg: Float = 0f,
    val location: Pair<Double, Double>? = null,
    val qiblaBearingDeg: Float? = null,
    val nearestMosque: MosqueDirectory.NearestResult? = null,
    val locationAvailable: Boolean = false,
    val loading: Boolean = false,
    val errorMessage: String? = null,
)
