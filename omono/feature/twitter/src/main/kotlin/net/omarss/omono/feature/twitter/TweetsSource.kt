package net.omarss.omono.feature.twitter

// Single-method contract the repository depends on. Mirrors the
// GPlaces / Docs / Quiz feature pattern: an interface in the public
// surface so DI can swap the production OkHttp impl for a fake in
// tests without exposing parsing internals.
interface TweetsSource {
    val isConfigured: Boolean

    /** Fetch one page. Empty list is a valid empty answer (don't throw). */
    suspend fun feed(request: FeedRequest): FeedPage
}

// FeedRequest mirrors the server's URL query params 1:1 so the layers
// stay easy to read. Empty `cities` means "no city filter"; blank
// `query` means "no keyword filter"; zero `limit` means "use the
// server default".
data class FeedRequest(
    val countries: List<Country>,
    val cities: List<String> = emptyList(),
    val query: String = "",
    val cursor: String? = null,
    val limit: Int = 60,
)

// FeedPage is one page of results plus the cursor the client passes
// back to fetch the next page. Empty `nextCursor` signals end-of-feed.
data class FeedPage(
    val tweets: List<Tweet>,
    val nextCursor: String? = null,
)
