package net.omarss.omono.feature.docs

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import javax.inject.Inject
import javax.inject.Singleton

// Thin pass-through + in-memory body cache for docs. The list
// responses are small (~N × ~150 bytes) so we don't cache them;
// individual doc bodies can be ~50 KB each and will commonly be
// re-opened while the user browses, so those do live in memory for
// the duration of the process.
//
// No disk cache yet — see FEEDBACK.md §11.8. ETag revalidation is a
// follow-up once the backend ships the header.
@Singleton
class DocsRepository @Inject constructor(
    private val client: DocsClient,
) {
    val isConfigured: Boolean get() = client.isConfigured

    private val mutex = Mutex()
    private val bodyCache = LinkedHashMap<CacheKey, Doc>()

    suspend fun subjects(): List<DocSubject> = client.subjects()

    suspend fun list(subject: String): List<DocSummary> = client.list(subject)

    // Returns the cached body when available, otherwise fetches and
    // populates the cache. The eviction rule is simple and dumb — we
    // cap the map at MAX_CACHED_DOCS and drop the oldest entry on
    // overflow. Good enough for a personal reading app.
    suspend fun fetch(subject: String, id: String): Doc? {
        val key = CacheKey(subject, id)
        mutex.withLock { bodyCache[key] }?.let { return it }

        val fetched = client.fetch(subject, id) ?: return null
        mutex.withLock {
            if (bodyCache.size >= MAX_CACHED_DOCS) {
                val oldest = bodyCache.keys.firstOrNull()
                if (oldest != null) bodyCache.remove(oldest)
            }
            bodyCache[key] = fetched
        }
        return fetched
    }

    private data class CacheKey(val subject: String, val id: String)

    private companion object {
        const val MAX_CACHED_DOCS = 16
    }
}
