package net.omarss.omono.feature.places

import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.math.abs

// Domain-facing API for the places feature. Wraps whichever
// PlacesSource the DI module selects (self-hosted GPlaces proxy by
// default, TomTom as fallback) and provides derived helpers
// (direction-cone filter, etc.) so the ViewModel doesn't need to know
// about backend specifics.
@Singleton
class PlacesRepository @Inject constructor(
    private val source: PlacesSource,
) {

    val isConfigured: Boolean get() = source.isConfigured

    suspend fun nearby(
        latitude: Double,
        longitude: Double,
        category: PlaceCategory,
        radiusMeters: Int,
    ): List<Place> = source.nearbySearch(
        latitude = latitude,
        longitude = longitude,
        radiusMeters = radiusMeters,
        category = category,
    )

    // `/v1/places` requires a single category per request, so "show me
    // everything in this area" becomes a parallel fan-out across all
    // categories. Results are deduped by `id` — a place that falls
    // under multiple server-side categories would otherwise appear
    // multiple times — and sorted by distance for the UI. Failures
    // from individual categories are swallowed so a single backend
    // hiccup doesn't empty the whole list.
    suspend fun nearbyAll(
        latitude: Double,
        longitude: Double,
        radiusMeters: Int,
    ): List<Place> = coroutineScope {
        PlaceCategory.entries
            .map { cat ->
                async {
                    runCatching {
                        source.nearbySearch(
                            latitude = latitude,
                            longitude = longitude,
                            radiusMeters = radiusMeters,
                            category = cat,
                        )
                    }.getOrDefault(emptyList())
                }
            }
            .awaitAll()
            .flatten()
            .distinctBy { it.id }
            .sortedBy { it.distanceMeters }
    }
}

// Pure filter — keeps places whose bearing from the user is within
// `coneDegrees` on either side of `heading`. `coneDegrees = 180` is
// effectively "no filter" (accepts everything). Handles wrap-around at
// 0°/360° correctly.
fun filterByDirection(
    places: List<Place>,
    heading: Float,
    coneDegrees: Float,
): List<Place> {
    if (coneDegrees >= 180f) return places
    return places.filter { place ->
        var delta = abs(place.bearingDegrees - heading)
        if (delta > 180f) delta = 360f - delta
        delta <= coneDegrees
    }
}
