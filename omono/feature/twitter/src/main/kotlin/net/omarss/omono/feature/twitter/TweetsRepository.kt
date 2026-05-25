package net.omarss.omono.feature.twitter

import javax.inject.Inject
import javax.inject.Singleton

// Thin pass-through, matching McqRepository / DocsRepository in shape.
// Exists so the ViewModel binds to a stable surface and so we have
// room to add an in-memory cache later (per-country, with a TTL) when
// the live source's response time becomes the user-visible cost.
@Singleton
class TweetsRepository @Inject constructor(
    private val source: TweetsSource,
) {
    val isConfigured: Boolean get() = source.isConfigured

    suspend fun feed(country: Country): List<Tweet> = source.feed(country)
}
