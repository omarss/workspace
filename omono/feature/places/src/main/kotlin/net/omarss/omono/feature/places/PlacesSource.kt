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

    // `category == null` means "all categories" — backends that
    // support it (gplaces v2 onward accepts `category=all`) should
    // serve the union in one call; others can fan out client-side.
    // `minRating` / `minReviews`, when non-null and > 0, filter the
    // response at the source so the client doesn't have to throw
    // away bytes it just downloaded.
    suspend fun nearbySearch(
        latitude: Double,
        longitude: Double,
        radiusMeters: Int,
        category: PlaceCategory?,
        limit: Int = 25,
        minRating: Float? = null,
        minReviews: Int? = null,
        // Offset into the ordered result set for pagination (see
        // omono's FEEDBACK.md §9.9). Today the server doesn't yet
        // honour it; it simply returns the same page each time. The
        // ViewModel uses response equality as a terminator so "endless
        // scroll" gracefully stops at the 50-result server cap until
        // pagination ships. Safe to pass in every request.
        offset: Int = 0,
    ): List<Place>

    // Full-text search across every category within the radius.
    // Backed by `/v1/search?q=...` — server fuzzy-matches on
    // name + address and returns a relevance-ordered list. Empty
    // query should return an empty list (the UI expects a typed
    // prompt before firing).
    suspend fun search(
        query: String,
        latitude: Double,
        longitude: Double,
        radiusMeters: Int,
        limit: Int = 25,
        offset: Int = 0,
    ): List<Place>
}
