package net.omarss.omono.ui.places

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
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import net.omarss.omono.feature.places.HeadingSensor
import net.omarss.omono.feature.places.Place
import net.omarss.omono.feature.places.PlaceCategory
import net.omarss.omono.feature.places.PlacesRepository
import net.omarss.omono.feature.places.filterByDirection
import timber.log.Timber
import javax.inject.Inject

@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class PlacesViewModel @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val repository: PlacesRepository,
    headingSensor: HeadingSensor,
) : ViewModel() {

    // `null` means "All categories" — the repository fans out in
    // parallel across every PlaceCategory. The default view on first
    // open is All so the user isn't funnelled into a single bucket.
    private val selectedCategory = MutableStateFlow<PlaceCategory?>(null)
    private val coneDegrees = MutableStateFlow(180f) // 180 = all directions
    private val radiusMeters = MutableStateFlow(5_000)
    private val searchQuery = MutableStateFlow("")
    // When on (default), hide low-signal places: rating < 4 OR
    // reviewCount < 100. Lots of the backend results are unrated
    // stubs; hiding them by default gives the list a much higher
    // signal-to-noise ratio.
    private val qualityFilter = MutableStateFlow(true)
    private val rawPlaces = MutableStateFlow<List<Place>>(emptyList())
    private val loading = MutableStateFlow(false)
    private val error = MutableStateFlow<String?>(null)
    // Last GPS fix — used to compute the qibla bearing and feed the
    // nearest-mosque query. Nullable because refresh may fail before
    // a fix arrives (no permission, airplane mode, etc.).
    private val currentLocation = MutableStateFlow<Pair<Double, Double>?>(null)
    private val nearestMosque = MutableStateFlow<Place?>(null)

    private val heading: StateFlow<Float> = headingSensor.headings()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), initialValue = 0f)

    val uiState: StateFlow<PlacesUiState> = combine(
        selectedCategory,
        coneDegrees,
        radiusMeters,
        rawPlaces,
        // Nested combine — Kotlin tops out at 5 direct args. Carries
        // search + quality + heading + loading + error + compass data
        // so the outer combine still stays within bounds.
        combine(
            combine(searchQuery, qualityFilter, heading) { q, qf, h ->
                Triple(q, qf, h)
            },
            combine(loading, error) { l, e -> l to e },
            combine(currentLocation, nearestMosque) { loc, mosque -> loc to mosque },
        ) { (q, qf, h), (l, e), (loc, mosque) ->
            CombinedExtras(q, qf, h, l, e, loc, mosque)
        },
    ) { category, cone, radius, places, extras ->
        val directionFiltered = filterByDirection(places, extras.heading, cone)
        val searchFiltered = applySearch(directionFiltered, extras.searchQuery)
        val qualityFiltered = if (extras.qualityFilter) {
            applyQualityFilter(searchFiltered)
        } else {
            searchFiltered
        }
        PlacesUiState(
            category = category,
            radiusMeters = radius,
            coneDegrees = cone,
            heading = extras.heading,
            places = qualityFiltered,
            searchQuery = extras.searchQuery,
            qualityFilter = extras.qualityFilter,
            qiblaBearing = extras.currentLocation?.let {
                qiblaBearingDeg(it.first, it.second).toFloat()
            },
            nearestMosque = extras.nearestMosque,
            loading = extras.loading,
            errorMessage = extras.error,
            configured = repository.isConfigured,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = PlacesUiState(),
    )

    private data class CombinedExtras(
        val searchQuery: String,
        val qualityFilter: Boolean,
        val heading: Float,
        val loading: Boolean,
        val error: String?,
        val currentLocation: Pair<Double, Double>?,
        val nearestMosque: Place?,
    )

    fun selectCategory(category: PlaceCategory?) {
        selectedCategory.value = category
        refresh()
    }

    fun setCone(degrees: Float) {
        coneDegrees.value = degrees
    }

    fun setRadius(meters: Int) {
        radiusMeters.value = meters
        refresh()
    }

    fun setSearchQuery(query: String) {
        searchQuery.value = query
    }

    fun setQualityFilter(enabled: Boolean) {
        qualityFilter.value = enabled
    }

    // Simple in-memory cache. When the user navigates back into the
    // places screen the existing results are reused instead of being
    // wiped to a loading spinner — eliminates the flicker where the
    // list briefly disappears on every re-open.
    //
    // A fetch is considered "fresh" when category + radius haven't
    // changed and the user is still in the same ~220 m grid bucket
    // and the last fetch was less than FRESH_WINDOW_MS ago. `force`
    // bypasses the cache for the refresh button / pull-to-refresh.
    private data class FetchKey(
        val category: PlaceCategory?,
        val radiusMeters: Int,
        val bucketLat: Int,
        val bucketLon: Int,
    )

    private var lastFetchKey: FetchKey? = null
    private var lastFetchAtMs: Long = 0L

    fun refresh(force: Boolean = false) {
        viewModelScope.launch {
            if (!hasLocationPermission()) {
                error.value = "Location permission needed"
                return@launch
            }
            if (!repository.isConfigured) {
                error.value = null
                rawPlaces.value = emptyList()
                return@launch
            }
            val location = fetchLocation() ?: run {
                if (rawPlaces.value.isEmpty()) error.value = "No GPS fix yet"
                return@launch
            }
            currentLocation.value = location
            // Fire the nearest-mosque query alongside the main list.
            // One extra HTTP call per refresh; the compass needs its
            // bearing and the user expects it to follow location.
            refreshNearestMosque(location)
            val key = FetchKey(
                category = selectedCategory.value,
                radiusMeters = radiusMeters.value,
                bucketLat = (location.first * BUCKETS_PER_DEGREE).toInt(),
                bucketLon = (location.second * BUCKETS_PER_DEGREE).toInt(),
            )
            val now = System.currentTimeMillis()
            val fresh = !force &&
                key == lastFetchKey &&
                now - lastFetchAtMs < FRESH_WINDOW_MS &&
                rawPlaces.value.isNotEmpty()
            if (fresh) return@launch

            loading.value = true
            error.value = null
            runCatching {
                val cat = selectedCategory.value
                if (cat == null) {
                    repository.nearbyAll(
                        latitude = location.first,
                        longitude = location.second,
                        radiusMeters = radiusMeters.value,
                    )
                } else {
                    repository.nearby(
                        latitude = location.first,
                        longitude = location.second,
                        category = cat,
                        radiusMeters = radiusMeters.value,
                    )
                }
            }
                .onSuccess { places ->
                    rawPlaces.value = places
                    error.value = null
                    lastFetchKey = key
                    lastFetchAtMs = now
                }
                .onFailure {
                    Timber.w(it, "Places lookup failed")
                    error.value = it.message ?: "Lookup failed"
                }
            loading.value = false
        }
    }

    // Case-insensitive substring search on place name + address so a
    // user typing "cafe" picks up both the name and address hits.
    private fun applySearch(places: List<Place>, query: String): List<Place> {
        val needle = query.trim().lowercase()
        if (needle.isEmpty()) return places
        return places.filter { place ->
            place.name.lowercase().contains(needle) ||
                place.address?.lowercase()?.contains(needle) == true
        }
    }

    // Quality gate: ≥ 4.0 stars AND ≥ 100 reviews. Both must be
    // present — an unrated place or a rated-but-barely-reviewed place
    // doesn't meet the bar. Matches what the user intuitively means
    // by "a place worth visiting".
    private fun applyQualityFilter(places: List<Place>): List<Place> = places.filter { place ->
        val rating = place.rating ?: return@filter false
        val reviews = place.reviewCount ?: return@filter false
        rating >= MIN_RATING && reviews >= MIN_REVIEW_COUNT
    }

    private companion object {
        // ~60 seconds inside the cache window = silent no-op on re-open.
        // The dashboard refresh button always forces a fresh fetch.
        const val FRESH_WINDOW_MS: Long = 60_000L

        // 500 buckets per degree ≈ 0.002° ≈ 220 m. A phone sitting on
        // the user's desk drifts within a bucket, so re-opening the
        // screen without moving doesn't re-fetch.
        const val BUCKETS_PER_DEGREE: Double = 500.0

        // Default quality bar — below this the list fills with half-
        // reviewed kiosks and closed venues.
        const val MIN_RATING: Float = 4.0f
        const val MIN_REVIEW_COUNT: Int = 100

        // Mosque-compass search radius. Roomy enough to always find
        // something in urban Riyadh; smaller and a user in a less-
        // dense part of the city would see an empty mosque marker.
        const val MOSQUE_SEARCH_RADIUS_M = 5_000
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

    // Dedicated fetch for the single nearest mosque so the compass
    // always has a sensible "where to pray" arrow regardless of the
    // category currently selected in the list. Failures are silent —
    // the marker just disappears.
    private suspend fun refreshNearestMosque(location: Pair<Double, Double>) {
        runCatching {
            repository.nearby(
                latitude = location.first,
                longitude = location.second,
                category = PlaceCategory.MOSQUE,
                radiusMeters = MOSQUE_SEARCH_RADIUS_M,
            )
        }.onSuccess { places ->
            nearestMosque.value = places.minByOrNull { it.distanceMeters }
        }.onFailure {
            Timber.w(it, "Nearest-mosque lookup failed")
        }
    }

}

data class PlacesUiState(
    val category: PlaceCategory? = null, // null = All
    val radiusMeters: Int = 5_000,
    val coneDegrees: Float = 180f,
    val heading: Float = 0f,
    val places: List<Place> = emptyList(),
    val searchQuery: String = "",
    val qualityFilter: Boolean = true,
    // true bearings in degrees from north, used by the compass rose.
    // Null until the first GPS fix arrives.
    val qiblaBearing: Float? = null,
    val nearestMosque: Place? = null,
    val loading: Boolean = false,
    val errorMessage: String? = null,
    val configured: Boolean = false,
)
