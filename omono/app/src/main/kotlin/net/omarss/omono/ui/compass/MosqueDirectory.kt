package net.omarss.omono.ui.compass

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONObject
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

// Offline directory of Riyadh mosques. Loaded once on first use from
// the bundled `assets/riyadh_mosques.json` asset — ≈2 k entries,
// ~100 KB on disk, ~300 KB heap once parsed into primitive arrays.
//
// Kept separate from the /v1/places integration because the backend
// mosque category is still sparse and won't survive the internet-
// kill-switch drive mode anyway. A bundled asset is the simplest way
// to guarantee the compass has a nearest-mosque bearing every tick.
@Singleton
class MosqueDirectory @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    private val mutex = Mutex()
    @Volatile private var entries: Array<Entry>? = null

    // Result of a nearest-mosque lookup. Bearing is in true degrees
    // from north (0 = north, 90 = east), the same frame as the
    // compass rose's markers.
    //
    // `cid` is populated only when the winner came from the backend
    // (gplaces) — the offline OSM directory has no Google Maps
    // place IDs. The UI uses it to pick between a `?cid=<n>` deep
    // link (place card with reviews) and a plain `geo:` pin.
    data class NearestResult(
        val name: String?,
        val latitude: Double,
        val longitude: Double,
        val distanceMeters: Double,
        val bearingDeg: Float,
        val cid: String? = null,
    )

    suspend fun nearestTo(userLat: Double, userLon: Double): NearestResult? {
        val loaded = ensureLoaded() ?: return null
        if (loaded.isEmpty()) return null

        // Bbox pre-filter — only compute haversine for mosques within
        // a rough degree window around the user. Cheap integer-ish
        // math on every entry, full geodesy on the handful that
        // survive. 0.1° ≈ 11 km in latitude — plenty for "nearest
        // mosque" without missing candidates.
        val searchDegLat = NEARBY_SEARCH_DEG
        val searchDegLon = NEARBY_SEARCH_DEG / cos(Math.toRadians(userLat)).coerceAtLeast(0.1)
        val latLo = (userLat - searchDegLat).toFloat()
        val latHi = (userLat + searchDegLat).toFloat()
        val lonLo = (userLon - searchDegLon).toFloat()
        val lonHi = (userLon + searchDegLon).toFloat()

        var bestDist = Double.POSITIVE_INFINITY
        var best: Entry? = null
        for (e in loaded) {
            if (e.lat < latLo || e.lat > latHi) continue
            if (e.lon < lonLo || e.lon > lonHi) continue
            val d = haversineMeters(userLat, userLon, e.lat.toDouble(), e.lon.toDouble())
            if (d < bestDist) {
                bestDist = d
                best = e
            }
        }
        // Fallback: if the bbox pre-filter turned up nothing (user
        // outside Riyadh bbox by a few hundred metres on the ring
        // road), do one full scan so we still return something.
        if (best == null) {
            for (e in loaded) {
                val d = haversineMeters(userLat, userLon, e.lat.toDouble(), e.lon.toDouble())
                if (d < bestDist) {
                    bestDist = d
                    best = e
                }
            }
        }
        val winner = best ?: return null
        return NearestResult(
            name = winner.name,
            latitude = winner.lat.toDouble(),
            longitude = winner.lon.toDouble(),
            distanceMeters = bestDist,
            bearingDeg = bearingDeg(
                userLat, userLon,
                winner.lat.toDouble(), winner.lon.toDouble(),
            ).toFloat(),
        )
    }

    private suspend fun ensureLoaded(): Array<Entry>? {
        entries?.let { return it }
        return mutex.withLock {
            entries ?: runCatching {
                withContext(Dispatchers.IO) { load() }
            }.onFailure {
                Timber.w(it, "MosqueDirectory load failed")
            }.getOrNull().also { entries = it }
        }
    }

    private fun load(): Array<Entry> {
        val json = context.assets.open(ASSET_NAME).bufferedReader().use { it.readText() }
        val root = JSONObject(json)
        val arr = root.optJSONArray("mosques") ?: return emptyArray()
        val out = ArrayList<Entry>(arr.length())
        for (i in 0 until arr.length()) {
            val item = arr.optJSONObject(i) ?: continue
            val lat = item.optDouble("lat", Double.NaN)
            val lon = item.optDouble("lon", Double.NaN)
            if (lat.isNaN() || lon.isNaN()) continue
            val name = if (item.has("n") && !item.isNull("n")) {
                item.optString("n").ifBlank { null }
            } else null
            out += Entry(lat = lat.toFloat(), lon = lon.toFloat(), name = name)
        }
        Timber.i("MosqueDirectory: loaded %d entries from %s", out.size, ASSET_NAME)
        return out.toTypedArray()
    }

    private data class Entry(
        val lat: Float,
        val lon: Float,
        val name: String?,
    )

    private companion object {
        const val ASSET_NAME = "riyadh_mosques.json"
        // 0.1° covers ~11 km N-S and ~10 km E-W at Riyadh's latitude.
        // Mosques are dense enough in the city that a nearest hit is
        // always inside this window; the fallback catches the rare
        // edge case.
        const val NEARBY_SEARCH_DEG = 0.1
    }
}

// Great-circle distance and initial bearing. Inline so this file
// doesn't depend on the feature/speed module (which has its own
// helpers behind `internal`).
private fun haversineMeters(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val r = 6_371_000.0
    val dLat = Math.toRadians(lat2 - lat1)
    val dLon = Math.toRadians(lon2 - lon1)
    val a = sin(dLat / 2).let { it * it } +
        cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) *
        sin(dLon / 2).let { it * it }
    val c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return min(r * c, Double.MAX_VALUE)
}

private fun bearingDeg(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val phi1 = Math.toRadians(lat1)
    val phi2 = Math.toRadians(lat2)
    val dLon = Math.toRadians(lon2 - lon1)
    val y = sin(dLon) * cos(phi2)
    val x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(dLon)
    val theta = Math.toDegrees(atan2(y, x))
    return (theta + 360.0) % 360.0
}
