package net.omarss.omono.feature.twitter

// Single-method contract the repository depends on. Mirrors the
// GPlaces / Docs / Quiz feature pattern: an interface in the public
// surface so DI can swap the production OkHttp impl for a fake in
// tests without exposing parsing internals.
interface TweetsSource {
    val isConfigured: Boolean

    // Returns the latest feed for the given country, sorted newest
    // first. Throws on transport / parse errors so the caller (the
    // repository) decides whether to surface or swallow. Returning an
    // empty list is a valid "no tweets right now" answer and must not
    // throw.
    suspend fun feed(country: Country): List<Tweet>
}
