package net.omarss.omono.feature.places

// Backend-agnostic contract for "give me POIs near here". The
// repository depends on this so we can swap TomTom (public API) for
// our self-hosted Google Places proxy without touching the UI.
//
// Implementations must return results sorted by distance ascending and
// must not throw on transport failure — prefer returning an empty list
// and logging. UI treats "no results" and "transport blew up" the same
// way from the user's perspective.
interface PlacesSource {

    // True when the source is reachable at all — e.g. the API key +
    // base URL are configured. PlacesRepository exposes this up to the
    // ViewModel so the UI can render a "not configured" empty state
    // instead of an error.
    val isConfigured: Boolean

    suspend fun nearbySearch(
        latitude: Double,
        longitude: Double,
        radiusMeters: Int,
        category: PlaceCategory,
        limit: Int = 25,
    ): List<Place>
}
