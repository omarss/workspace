package net.omarss.omono.feature.prayer

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

// Loads the bundled question pool and hands out random samples for
// the Fajr dismiss gate. Pool is lazily loaded once per process —
// the JSON files are tiny (a few KB each) but lazy still avoids
// touching the asset manager until the gate actually fires.
@Singleton
class ChallengeRepository @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    private val mutex = Mutex()
    private var cached: List<Challenge>? = null

    suspend fun all(): List<Challenge> = mutex.withLock {
        cached?.let { return@withLock it }
        val loaded = withContext(Dispatchers.IO) { loadAllFromAssets() }
        cached = loaded
        loaded
    }

    suspend fun sample(n: Int = FAJR_CHALLENGE_REQUIRED): List<Challenge> {
        val pool = all()
        if (pool.isEmpty()) return emptyList()
        return pool.shuffled().take(n.coerceAtMost(pool.size))
    }

    private fun loadAllFromAssets(): List<Challenge> {
        val out = ArrayList<Challenge>()
        val names = runCatching { context.assets.list(CHALLENGE_DIR)?.toList().orEmpty() }
            .getOrNull().orEmpty()
            .filter { it.endsWith(".json", ignoreCase = true) }
        for (name in names) {
            val path = "$CHALLENGE_DIR/$name"
            runCatching {
                val text = context.assets.open(path).bufferedReader().use { it.readText() }
                parseFile(text).let(out::addAll)
            }.onFailure { Timber.w(it, "ChallengeRepository: parse failed for %s", path) }
        }
        Timber.i("ChallengeRepository: loaded %d challenges from %d files", out.size, names.size)
        return out
    }

    // Public for test reuse. Accepts either a top-level JSON array
    // of challenge objects or `{ "challenges": [...] }` — the latter
    // is nicer for hand-curated files because it documents the
    // schema at the top of the file.
    internal fun parseFile(json: String): List<Challenge> {
        val root = runCatching { JSONObject(json) }.getOrNull()
        val arr: JSONArray = when {
            root != null && root.has("challenges") -> root.getJSONArray("challenges")
            else -> runCatching { JSONArray(json) }.getOrNull() ?: return emptyList()
        }
        val out = ArrayList<Challenge>(arr.length())
        for (i in 0 until arr.length()) {
            val item = arr.optJSONObject(i) ?: continue
            val c = parseChallenge(item) ?: continue
            out += c
        }
        return out
    }

    private fun parseChallenge(item: JSONObject): Challenge? {
        val id = item.optString("id").ifBlank { return null }
        val category = ChallengeCategory.fromStorage(item.optString("category"))
            ?: return null
        val stem = item.optString("stem").ifBlank { return null }
        val optsArr = item.optJSONArray("options") ?: return null
        val options = (0 until optsArr.length()).mapNotNull {
            optsArr.optString(it).takeIf { s -> s.isNotBlank() }
        }
        if (options.size !in 2..6) return null
        val correct = item.optInt("correct", -1)
        if (correct !in options.indices) return null
        val explanation = item.optString("explanation").takeIf { it.isNotBlank() }
        return runCatching {
            Challenge(
                id = id,
                category = category,
                stem = stem,
                options = options,
                correctIndex = correct,
                explanation = explanation,
            )
        }.getOrNull()
    }

    private companion object {
        const val CHALLENGE_DIR = "challenges"
    }
}
