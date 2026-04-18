package net.omarss.omono.ui.compass

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import net.omarss.omono.feature.places.HeadingSensor
import timber.log.Timber
import javax.inject.Inject

// Dedicated compass tab. Owns:
//   - the magnetometer stream (HeadingSensor),
//   - a one-shot GPS fix on load (refreshed when the user taps the
//     refresh button — heading is cheap, location is not),
//   - the qibla bearing derived from the fix, and
//   - the nearest-mosque bearing/name from the offline directory.
//
// Kept independent of PlacesViewModel so the compass works even if
// the user hasn't opened Places yet, and so the internet-kill-switch
// during drives doesn't break it.
@HiltViewModel
class CompassViewModel @Inject constructor(
    @param:ApplicationContext private val context: Context,
    headingSensor: HeadingSensor,
    private val mosqueDirectory: MosqueDirectory,
) : ViewModel() {

    private val heading: StateFlow<Float> = headingSensor.headings()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), initialValue = 0f)

    private val location = MutableStateFlow<Pair<Double, Double>?>(null)
    private val nearestMosque = MutableStateFlow<MosqueDirectory.NearestResult?>(null)
    private val errorMessage = MutableStateFlow<String?>(null)
    private val loading = MutableStateFlow(false)

    val uiState: StateFlow<CompassUiState> = combine(
        heading,
        location,
        nearestMosque,
        loading,
        errorMessage,
    ) { h, loc, mosque, isLoading, err ->
        CompassUiState(
            headingDeg = h,
            location = loc,
            qiblaBearingDeg = loc?.let { qiblaBearingDeg(it.first, it.second).toFloat() },
            nearestMosque = mosque,
            loading = isLoading,
            errorMessage = err,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = CompassUiState(),
    )

    init {
        // Auto-refresh on construction so the user lands on a useful
        // compass immediately; they can still tap refresh to re-query.
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            if (!hasLocationPermission()) {
                errorMessage.value = "Location permission needed"
                return@launch
            }
            loading.value = true
            errorMessage.value = null
            val fix = fetchLocation()
            if (fix == null) {
                errorMessage.value = "No GPS fix yet"
                loading.value = false
                return@launch
            }
            location.value = fix
            val nearest = runCatching {
                mosqueDirectory.nearestTo(fix.first, fix.second)
            }.onFailure { Timber.w(it, "Mosque lookup failed") }
                .getOrNull()
            nearestMosque.value = nearest
            loading.value = false
        }
    }

    private fun hasLocationPermission(): Boolean =
        ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.ACCESS_FINE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission")
    private suspend fun fetchLocation(): Pair<Double, Double>? {
        val client = LocationServices.getFusedLocationProviderClient(context)
        val cts = com.google.android.gms.tasks.CancellationTokenSource()
        val loc: android.location.Location? = runCatching {
            client.getCurrentLocation(Priority.PRIORITY_HIGH_ACCURACY, cts.token).await()
        }.getOrNull()
        return loc?.let { Pair(it.latitude, it.longitude) }
    }
}

data class CompassUiState(
    val headingDeg: Float = 0f,
    val location: Pair<Double, Double>? = null,
    val qiblaBearingDeg: Float? = null,
    val nearestMosque: MosqueDirectory.NearestResult? = null,
    val loading: Boolean = false,
    val errorMessage: String? = null,
)
