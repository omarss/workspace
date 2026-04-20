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
import net.omarss.omono.feature.places.Place
import net.omarss.omono.feature.places.PlaceCategory
import net.omarss.omono.feature.places.PlacesRepository
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
    private val placesRepository: PlacesRepository,
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

    // User-selected quick-access place categories. Each enabled entry
    // resolves to a "nearest of this kind" pin on the compass — same
    // model as the mosque row, but driven by the gplaces backend.
    // In-memory-only for now; persisted to DataStore would be a
    // follow-up if users end up picking a consistent set.
    private val enabledCategories = MutableStateFlow<Set<PlaceCategory>>(emptySet())
    private val nearbyCategoryPlaces =
        MutableStateFlow<Map<PlaceCategory, CategoryPlaceSnapshot>>(emptyMap())
    @Volatile private var lastCategoryLookupFix: AppLocationStream.Fix? = null

    val uiState: StateFlow<CompassUiState> = combine(
        heading,
        fix,
        mosqueIdentity,
        enabledCategories,
        nearbyCategoryPlaces,
    ) { h, f, mosque, enabled, nearby ->
        val qibla = f?.let { qiblaBearingDeg(it.latitude, it.longitude).toFloat() }
        val mosqueBearing = if (f != null && mosque != null) {
            bearingDeg(f.latitude, f.longitude, mosque.latitude, mosque.longitude).toFloat()
        } else null
        val mosqueDistance = if (f != null && mosque != null) {
            haversineMeters(f.latitude, f.longitude, mosque.latitude, mosque.longitude)
        } else null
        // Recompute each enabled category's bearing from the *current*
        // fix so the arrow reacts live to movement, same pattern as the
        // mosque row above. The identity / distance snapshot is only
        // refreshed on sparse location triggers — see
        // refreshCategoriesIfNeeded.
        val categoryRows = enabled.mapNotNull { cat ->
            val snap = nearby[cat] ?: return@mapNotNull null
            val b = f?.let {
                bearingDeg(it.latitude, it.longitude, snap.latitude, snap.longitude).toFloat()
            }
            val d = f?.let {
                haversineMeters(it.latitude, it.longitude, snap.latitude, snap.longitude)
            }
            if (b == null || d == null) return@mapNotNull null
            CategoryRow(
                category = cat,
                name = snap.name,
                latitude = snap.latitude,
                longitude = snap.longitude,
                cid = snap.cid,
                distanceMeters = d,
                bearingDeg = b,
            )
        }.sortedBy { it.distanceMeters }
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
                    cid = mosque.cid,
                )
            } else null,
            enabledCategories = enabled,
            categoryRows = categoryRows,
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
            .onEach {
                refreshMosqueIfNeeded()
                refreshCategoriesIfNeeded()
            }
            .launchIn(viewModelScope)

        // Toggle a new category on → fire an immediate lookup so the
        // row populates without waiting for the next movement bucket.
        enabledCategories
            .onEach { refreshCategoriesIfNeeded(force = true) }
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

        // Two candidate sources: the bundled OSM directory (offline,
        // fast, comprehensive for Riyadh but may lag on new mosques)
        // and the gplaces backend (live-scraped, richer metadata via
        // CID, but sometimes missing coords). Take whichever is
        // genuinely nearer to the user's current fix — that's the
        // right answer regardless of which catalogue has better
        // coverage in their neighbourhood. Either source failing
        // (e.g. geofence blocking the backend) is tolerated — we
        // just use whatever succeeded.
        val offline = runCatching {
            mosqueDirectory.nearestTo(current.latitude, current.longitude)
        }.onFailure { Timber.w(it, "MosqueDirectory lookup failed") }
            .getOrNull()
            ?.let {
                MosqueSnapshot(
                    name = it.name,
                    latitude = it.latitude,
                    longitude = it.longitude,
                    cid = null,
                )
            }

        val online = if (placesRepository.isConfigured) {
            runCatching {
                placesRepository.nearby(
                    latitude = current.latitude,
                    longitude = current.longitude,
                    category = PlaceCategory.MOSQUE,
                    radiusMeters = CATEGORY_RADIUS_M,
                    minRating = null,
                    minReviews = null,
                    limit = CATEGORY_CANDIDATES,
                )
            }.onFailure {
                Timber.w(it, "Backend mosque lookup failed")
            }.getOrNull()
                ?.firstOrNull(::isOpenEnough)
                ?.let {
                    MosqueSnapshot(
                        name = it.name,
                        latitude = it.latitude,
                        longitude = it.longitude,
                        cid = it.cid,
                    )
                }
        } else null

        mosqueIdentity.value = pickNearer(current, offline, online)
    }

    private fun pickNearer(
        fix: AppLocationStream.Fix,
        a: MosqueSnapshot?,
        b: MosqueSnapshot?,
    ): MosqueSnapshot? {
        if (a == null) return b
        if (b == null) return a
        val da = haversineMeters(fix.latitude, fix.longitude, a.latitude, a.longitude)
        val db = haversineMeters(fix.latitude, fix.longitude, b.latitude, b.longitude)
        return if (da <= db) a else b
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
        // Google Maps CID when the nearest mosque came from the
        // backend (new `?cid=<n>` deep link opens the place card with
        // reviews / hours). Null when the winner came from the
        // offline OSM directory, in which case the tap handler falls
        // back to a labelled `geo:` pin.
        val cid: String? = null,
    )

    // One row's worth of identity / position for a place-categories
    // pin. The bearing + distance shown on screen are derived live
    // from the current fix; this only carries enough to avoid
    // re-querying the backend on every heading tick. The `cid`
    // survives here so the tap handler can deep-link to Google Maps'
    // full place card (reviews / photos / hours) instead of dropping
    // the user into turn-by-turn navigation.
    private data class CategoryPlaceSnapshot(
        val name: String,
        val latitude: Double,
        val longitude: Double,
        val cid: String?,
    )

    fun toggleCategory(category: PlaceCategory) {
        val current = enabledCategories.value
        enabledCategories.value = if (category in current) current - category else current + category
    }

    private suspend fun refreshCategoriesIfNeeded(force: Boolean = false) {
        val current = fix.value ?: return
        val enabled = enabledCategories.value
        if (enabled.isEmpty()) {
            if (nearbyCategoryPlaces.value.isNotEmpty()) nearbyCategoryPlaces.value = emptyMap()
            return
        }
        if (!force) {
            val last = lastCategoryLookupFix
            if (last != null) {
                val moved = haversineMeters(
                    last.latitude, last.longitude,
                    current.latitude, current.longitude,
                )
                // Same cadence as the mosque refresh: tight enough that
                // driving past the nearest pharmacy flips the pin to
                // the next one before you've gone a block, loose enough
                // that a stopped phone doesn't hammer the backend.
                val alreadyFetched = nearbyCategoryPlaces.value.keys.containsAll(enabled)
                if (moved < CATEGORY_REFRESH_M && alreadyFetched) return
            }
        }
        if (!placesRepository.isConfigured) return
        lastCategoryLookupFix = current

        // One request per enabled category. The set is user-toggled and
        // expected to stay small (handful of pins), so sequential is
        // fine — no need to add a parallelising helper for this.
        // We ask for a small page (not just the single nearest) so that
        // if the literal nearest place is closed we can still surface
        // the next-nearest open one rather than rendering nothing.
        val updated = nearbyCategoryPlaces.value.toMutableMap()
        for (category in enabled) {
            val result = runCatching {
                placesRepository.nearby(
                    latitude = current.latitude,
                    longitude = current.longitude,
                    category = category,
                    radiusMeters = CATEGORY_RADIUS_M,
                    minRating = null,
                    minReviews = null,
                    limit = CATEGORY_CANDIDATES,
                )
            }.onFailure {
                Timber.w(it, "Compass nearest-%s lookup failed", category.name)
            }.getOrNull() ?: continue
            val nearest = result.firstOrNull(::isOpenEnough)
            if (nearest != null) {
                updated[category] = nearest.toSnapshot()
            } else {
                // No non-closed candidate in the page — drop any stale
                // entry so the row doesn't point at a place that's
                // since been flagged closed.
                updated.remove(category)
            }
        }
        // Drop entries for categories the user has since disabled so the
        // UI doesn't keep a stale row hanging around after untoggling.
        updated.keys.retainAll(enabled)
        nearbyCategoryPlaces.value = updated
    }

    // The compass is a driver-aid surface — routing a user to a place
    // that's permanently or temporarily closed is worse than showing
    // nothing. We filter both the explicit `business_status` closures
    // and the `open_now == false` signal. Places with `null` signals
    // (Google didn't surface one) are allowed through — most of the
    // current scrape data falls in that bucket and dropping them all
    // would leave the compass empty for a long time.
    private fun isOpenEnough(place: Place): Boolean {
        val status = place.businessStatus?.uppercase()
        if (status == "CLOSED_TEMPORARILY" || status == "CLOSED_PERMANENTLY") return false
        if (place.openNow == false) return false
        return true
    }

    private fun Place.toSnapshot() = CategoryPlaceSnapshot(
        name = name,
        latitude = latitude,
        longitude = longitude,
        cid = cid,
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

        // Nearest-X category pins reuse the same "refresh once we've
        // moved enough to plausibly change the answer" pattern. 75 m
        // is a slightly looser threshold than the mosque one because
        // hitting the backend is ~100× more expensive than reading
        // the on-disk mosque directory — no need to over-spin.
        const val CATEGORY_REFRESH_M = 75.0

        // Search radius for each nearest-X lookup. 5 km is wide enough
        // to cover the user's neighbourhood for urban categories (gyms,
        // pharmacies) and to reach the nearest metro station from most
        // of Riyadh, without the backend returning so many candidates
        // that the "first" entry isn't actually the nearest.
        const val CATEGORY_RADIUS_M = 5_000

        // Small candidate page per category — enough headroom for the
        // open-filter to fall through the literal nearest result when
        // it's flagged closed.
        const val CATEGORY_CANDIDATES = 10
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
    // Quick-access nearby categories the user has toggled on, plus the
    // resolved nearest place for each. enabledCategories is authoritative
    // for which chips are "on"; categoryRows only contains resolved
    // lookups so the UI renders whatever's actually pinpointed.
    val enabledCategories: Set<PlaceCategory> = emptySet(),
    val categoryRows: List<CategoryRow> = emptyList(),
    val locationAvailable: Boolean = false,
    val loading: Boolean = false,
    val errorMessage: String? = null,
)

// Resolved nearest-of-category row for the compass UI. Same shape as
// MosqueDirectory.NearestResult but kept separate so the two types
// can't be accidentally crossed (mosque directory is an on-disk asset
// with no rating / backend info).
data class CategoryRow(
    val category: PlaceCategory,
    val name: String,
    val latitude: Double,
    val longitude: Double,
    // Google Maps CID when the backend supplied one. The UI prefers a
    // `?cid=<n>` deep link so tapping the row opens the place's full
    // card (reviews, photos, hours) rather than raw turn-by-turn nav.
    val cid: String?,
    val distanceMeters: Double,
    val bearingDeg: Float,
)
