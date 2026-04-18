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
import kotlinx.coroutines.flow.catch
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
import net.omarss.omono.location.AppLocationStream
import timber.log.Timber
import javax.inject.Inject
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

@OptIn(ExperimentalCoroutinesApi::class, FlowPreview::class)
@HiltViewModel
class PlacesViewModel @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val repository: PlacesRepository,
    headingSensor: HeadingSensor,
    private val locationStream: AppLocationStream,
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
    private val loadingMore = MutableStateFlow(false)
    // Set to false once a pagination attempt returns nothing new —
    // either the server doesn't yet support offset (FEEDBACK.md §9.9)
    // or we've truly reached the end. Either way: stop firing more
    // scroll-triggered fetches until the query key changes.
    private val canLoadMore = MutableStateFlow(true)
    private val error = MutableStateFlow<String?>(null)

    private val heading: StateFlow<Float> = headingSensor.headings()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), initialValue = 0f)

    val uiState: StateFlow<PlacesUiState> = combine(
        selectedCategory,
        coneDegrees,
        radiusMeters,
        rawPlaces,
        combine(
            searchQuery,
            qualityFilter,
            heading,
            loading,
            combine(error, loadingMore, canLoadMore) { e, lm, cm -> Triple(e, lm, cm) },
        ) { q, qf, h, l, trio ->
            CombinedExtras(
                searchQuery = q,
                qualityFilter = qf,
                heading = h,
                loading = l,
                error = trio.first,
                loadingMore = trio.second,
                canLoadMore = trio.third,
            )
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
            loadingMore = extras.loadingMore,
            canLoadMore = extras.canLoadMore,
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
        val loadingMore: Boolean,
        val canLoadMore: Boolean,
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

        // Follow the shared location stream. When the user moves
        // LOCATION_REFRESH_M since the last fetch, kick off a fresh
        // nearby/search query so the list tracks movement instead of
        // showing stale "places near where I opened the tab" results.
        //
        // `force = true` because the 220 m cache bucket is coarser
        // than LOCATION_REFRESH_M, so without it a 150 m move would
        // land in the same bucket and short-circuit against the
        // freshness window.
        locationStream.updates()
            .catch { Timber.w(it, "Places location stream failed") }
            .onEach { fix ->
                val last = lastFetchLocation
                val shouldRefresh = last == null ||
                    haversineMeters(
                        last.first, last.second,
                        fix.latitude, fix.longitude,
                    ) >= LOCATION_REFRESH_M
                if (shouldRefresh) refresh(force = true)
            }
            .launchIn(viewModelScope)
    }

    @Volatile private var lastFetchLocation: Pair<Double, Double>? = null

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
                fetchPage(
                    query = query,
                    location = location,
                    offset = 0,
                )
            }
                .onSuccess { places ->
                    rawPlaces.value = places
                    error.value = null
                    lastFetchKey = key
                    lastFetchAtMs = now
                    lastFetchLocation = location
                    // Reset pagination — a fresh query starts from 0.
                    // Assume more is available; the first loadMore call
                    // will flip the flag once it sees no new rows.
                    canLoadMore.value = places.isNotEmpty() && places.size >= PAGE_SIZE
                }
                .onFailure {
                    Timber.w(it, "Places lookup failed")
                    error.value = it.message ?: "Lookup failed"
                }
            loading.value = false
        }
    }

    // Called when the user scrolls near the end of the LazyColumn.
    // Appends the next page's results to `rawPlaces`. Deduplicates by
    // place id so a server that doesn't yet honour the offset param
    // (FEEDBACK.md §9.9) can't create duplicate rows — and if the
    // server returns no new rows we flip `canLoadMore` off so scroll
    // stops asking for more.
    fun loadMore() {
        if (!canLoadMore.value) return
        if (loadingMore.value || loading.value) return
        val existing = rawPlaces.value
        if (existing.isEmpty()) return
        viewModelScope.launch {
            val location = lastFetchLocation ?: fetchLocation() ?: return@launch
            val query = searchQuery.value.trim()
            loadingMore.value = true
            val result = runCatching {
                fetchPage(
                    query = query,
                    location = location,
                    offset = existing.size,
                )
            }.onFailure {
                Timber.w(it, "Places load-more failed")
            }.getOrNull().orEmpty()
            val existingIds = existing.mapTo(HashSet()) { it.id }
            val newOnes = result.filter { it.id !in existingIds }
            if (newOnes.isEmpty()) {
                // Server didn't advance the cursor (likely the pagination
                // ask in FEEDBACK.md §9.9 isn't live yet) or we hit the
                // real end. Either way, stop pulling.
                canLoadMore.value = false
            } else {
                rawPlaces.value = existing + newOnes
                canLoadMore.value = newOnes.size >= PAGE_SIZE
            }
            loadingMore.value = false
        }
    }

    // Single server round-trip shared by the initial load and the
    // load-more path. `/v1/search` now honours `min_rating` +
    // `min_reviews` server-side (FEEDBACK.md §9.4-bug, verified live
    // 2026-04-18) so the old client-side fallback is gone. `PAGE_SIZE`
    // equals the backend's current hard cap of 50 so we pull as much
    // as possible per call.
    private suspend fun fetchPage(
        query: String,
        location: Pair<Double, Double>,
        offset: Int,
    ): List<Place> {
        return if (query.isNotEmpty()) {
            repository.search(
                query = query,
                latitude = location.first,
                longitude = location.second,
                radiusMeters = radiusMeters.value,
                limit = PAGE_SIZE,
                offset = offset,
            )
        } else {
            repository.nearby(
                latitude = location.first,
                longitude = location.second,
                category = selectedCategory.value,
                radiusMeters = radiusMeters.value,
                minRating = if (qualityFilter.value) MIN_RATING else null,
                minReviews = if (qualityFilter.value) MIN_REVIEW_COUNT else null,
                limit = PAGE_SIZE,
                offset = offset,
            )
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

        // Re-fetch once the user has moved this far from wherever we
        // last pulled results. 150 m is big enough to ignore GPS
        // wander at a stoplight, small enough that walking past a
        // block re-lists the places around you.
        const val LOCATION_REFRESH_M: Double = 150.0

        // Page size for each backend call. The gplaces server caps at
        // 50 per response (see FEEDBACK.md §9.1 / §9.9), so we request
        // the full cap per page and lean on offset pagination — once
        // the server supports it — for anything beyond that.
        const val PAGE_SIZE: Int = 50
    }

    // Client-side mirror of the backend's `min_rating` + `min_reviews`
    // gate. Identical semantics: a place must have a rating ≥ 4, a
    // review_count ≥ 100, and both must be non-null (unrated places
    // fail the filter). Used only on the /v1/search code path while
    // the server-side implementation isn't honouring the params.
    private fun passesQualityGate(place: Place): Boolean {
        val rating = place.rating ?: return false
        val reviews = place.reviewCount ?: return false
        return rating >= MIN_RATING && reviews >= MIN_REVIEW_COUNT
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

// Great-circle distance. Kept private to this file because the
// ViewModel only needs it for the "did we move enough to re-fetch"
// check — unrelated to the repository's own filter geometry.
private fun haversineMeters(
    lat1: Double, lon1: Double,
    lat2: Double, lon2: Double,
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

data class PlacesUiState(
    val category: PlaceCategory? = null, // null = All
    val radiusMeters: Int = 5_000,
    val coneDegrees: Float = 180f,
    val heading: Float = 0f,
    val places: List<Place> = emptyList(),
    val searchQuery: String = "",
    val qualityFilter: Boolean = true,
    val loading: Boolean = false,
    // True while the endless-scroll path is fetching the next page.
    // Distinct from `loading` (first load / query change) so the UI
    // can show a spinner below the list without hiding existing rows.
    val loadingMore: Boolean = false,
    val canLoadMore: Boolean = false,
    val errorMessage: String? = null,
    val configured: Boolean = false,
)
