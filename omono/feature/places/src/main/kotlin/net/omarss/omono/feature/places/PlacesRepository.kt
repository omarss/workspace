package net.omarss.omono.feature.places

import javax.inject.Inject
import javax.inject.Singleton
import kotlin.math.abs

// Domain-facing API for the places feature. Wraps TomTomSearchClient
// and provides derived helpers (direction-cone filter, etc.) so the
// ViewModel doesn't need to know about TomTom specifics.
@Singleton
class PlacesRepository @Inject constructor(
    private val client: TomTomSearchClient,
) {

    val isConfigured: Boolean get() = client.isConfigured

    suspend fun nearby(
        latitude: Double,
        longitude: Double,
        category: PlaceCategory,
        radiusMeters: Int,
    ): List<Place> = client.nearbySearch(
        latitude = latitude,
        longitude = longitude,
        radiusMeters = radiusMeters,
        category = category,
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
