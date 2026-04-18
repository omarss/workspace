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
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
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

@OptIn(ExperimentalCoroutinesApi::class, FlowPreview::class)
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

    private val heading: StateFlow<Float> = headingSensor.headings()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), initialValue = 0f)

    val uiState: StateFlow<PlacesUiState> = combine(
        selectedCategory,
        coneDegrees,
        radiusMeters,
        rawPlaces,
        combine(searchQuery, qualityFilter, heading, loading, error) { q, qf, h, l, e ->
            CombinedExtras(q, qf, h, l, e)
        },
    ) { category, cone, radius, places, extras ->
        val directionFiltered = filterByDirection(places, extras.heading, cone)
        // Both search and quality filter run server-side now — the
        // `q`, `min_rating`, `min_reviews` params in refresh() do
        // the work. Only direction is applied client-side because
        // it depends on the live magnetometer.
        PlacesUiState(
            category = category,
            radiusMeters = radius,
            coneDegrees = cone,
            heading = extras.heading,
            places = directionFiltered,
            searchQuery = extras.searchQuery,
            qualityFilter = extras.qualityFilter,
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
        // Filter is server-side — toggling it changes the payload,
        // so kick off a fresh fetch instead of relying on the cache.
        refresh()
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
        val qualityFilter: Boolean,
        val searchQuery: String,
    )

    init {
        // Debounced auto-refresh on typed-query changes. Drop(1) skips
        // the initial empty value so the constructor doesn't fire a
        // redundant fetch before the UI has even mounted.
        searchQuery
            .drop(1)
            .distinctUntilChanged()
            .debounce(300)
            .onEach { refresh() }
            .launchIn(viewModelScope)
    }

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
            val query = searchQuery.value.trim()
            val key = FetchKey(
                category = selectedCategory.value,
                radiusMeters = radiusMeters.value,
                bucketLat = (location.first * BUCKETS_PER_DEGREE).toInt(),
                bucketLon = (location.second * BUCKETS_PER_DEGREE).toInt(),
                qualityFilter = qualityFilter.value,
                searchQuery = query,
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
                if (query.isNotEmpty()) {
                    // Typed query → hit the server-side full-text
                    // endpoint, which matches against name, address,
                    // and the review snippet Google supplies.
                    // Results come back in relevance order.
                    repository.search(
                        query = query,
                        latitude = location.first,
                        longitude = location.second,
                        radiusMeters = radiusMeters.value,
                    )
                } else {
                    // `category=null` here → gplaces `category=all`,
                    // one HTTP call for the union. Quality filter is
                    // server-side so the payload is already trimmed
                    // to 4★ / 100 reviews when the toggle is on.
                    repository.nearby(
                        latitude = location.first,
                        longitude = location.second,
                        category = selectedCategory.value,
                        radiusMeters = radiusMeters.value,
                        minRating = if (qualityFilter.value) MIN_RATING else null,
                        minReviews = if (qualityFilter.value) MIN_REVIEW_COUNT else null,
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

data class PlacesUiState(
    val category: PlaceCategory? = null, // null = All
    val radiusMeters: Int = 5_000,
    val coneDegrees: Float = 180f,
    val heading: Float = 0f,
    val places: List<Place> = emptyList(),
    val searchQuery: String = "",
    val qualityFilter: Boolean = true,
    val loading: Boolean = false,
    val errorMessage: String? = null,
    val configured: Boolean = false,
)
