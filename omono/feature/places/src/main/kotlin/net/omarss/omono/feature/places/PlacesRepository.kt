package net.omarss.omono.feature.places

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

    // `category == null` → union of all categories (server-side
    // via `category=all`). `minRating` / `minReviews`, when > 0,
    // filter at the source. See FEEDBACK.md §9.1 / §9.2 — previously
    // we fanned out N parallel calls + filtered client-side; the
    // backend handles both now.
    suspend fun nearby(
        latitude: Double,
        longitude: Double,
        category: PlaceCategory?,
        radiusMeters: Int,
        minRating: Float? = null,
        minReviews: Int? = null,
        limit: Int = 25,
        offset: Int = 0,
    ): List<Place> = source.nearbySearch(
        latitude = latitude,
        longitude = longitude,
        radiusMeters = radiusMeters,
        category = category,
        limit = limit,
        minRating = minRating,
        minReviews = minReviews,
        offset = offset,
    )

    suspend fun search(
        query: String,
        latitude: Double,
        longitude: Double,
        radiusMeters: Int,
        limit: Int = 25,
        offset: Int = 0,
    ): List<Place> = source.search(
        query = query,
        latitude = latitude,
        longitude = longitude,
        radiusMeters = radiusMeters,
        limit = limit,
        offset = offset,
    )
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
