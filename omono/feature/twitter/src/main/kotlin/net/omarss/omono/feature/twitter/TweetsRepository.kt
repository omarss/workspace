package net.omarss.omono.feature.twitter

import javax.inject.Inject
import javax.inject.Singleton

// Thin pass-through repository, matching McqRepository / DocsRepository
// in shape. Exists so the ViewModel binds to a stable surface and so
// we have a single point at which to add caching / retry / etc. later
// without rewiring the UI.
@Singleton
class TweetsRepository @Inject constructor(
    private val source: TweetsSource,
) {
    val isConfigured: Boolean get() = source.isConfigured

    suspend fun feed(request: FeedRequest): FeedPage = source.feed(request)
}
