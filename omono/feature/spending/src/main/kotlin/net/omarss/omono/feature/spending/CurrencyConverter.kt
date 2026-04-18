package net.omarss.omono.feature.spending

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import timber.log.Timber
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

// Converts foreign-currency transaction amounts into SAR. Tries the
// XE-equivalent live daily rates first (frankfurter.app serves free
// ECB reference rates — no auth, no card, mirrors XE's mid-market
// figures within a fraction of a percent). On network failure or
// missing currency it falls back to the SAMA peg for USD (1 USD =
// 3.75 SAR, unchanged for decades) and a small static snapshot for
// the other GCC / European codes that show up in the SMS stream.
//
// Rates are fetched lazily on first use and cached for REFRESH_MILLIS
// so we don't hit the network on every transaction parse.
@Singleton
class CurrencyConverter @Inject constructor() {

    @Volatile private var cachedRates: Map<String, Double> = STATIC_RATES
    @Volatile private var cachedAt: Long = 0L
    private val mutex = Mutex()

    private val http: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(5, TimeUnit.SECONDS)
            .build()
    }

    // Preloads live rates once per day. Safe to call on any dispatcher
    // — the actual network work happens on IO. Repository callers
    // should invoke this once before a batch parse so every parsed
    // transaction converts against the same snapshot.
    suspend fun refreshIfStale() {
        val now = System.currentTimeMillis()
        if (now - cachedAt < REFRESH_MILLIS) return
        mutex.withLock {
            if (now - cachedAt < REFRESH_MILLIS) return
            val fetched = fetchLiveRates()
            if (fetched.isNotEmpty()) {
                // Merge live into static so any currencies the live
                // feed omits still resolve via the snapshot fallback.
                cachedRates = STATIC_RATES + fetched
                cachedAt = now
            } else if (cachedAt == 0L) {
                // First call and the fetch failed — mark the cache as
                // populated with the static fallback so we don't hammer
                // the network on every subsequent call.
                cachedAt = now
            }
        }
    }

    // Returns the SAR equivalent for the given foreign amount. Falls
    // back to the original amount if the currency isn't recognised —
    // better to under-count than to silently drop a row.
    fun toSar(amount: Double, currency: String): Double = convert(amount, currency).amountSar

    // Same conversion with a flag indicating whether we had a real
    // rate available. Callers that want to surface "FX unavailable"
    // to the user (repository → Transaction.fxFailed) use this;
    // the plain toSar() above stays for back-compat with tests.
    fun convert(amount: Double, currency: String): Conversion {
        val code = canonicalize(currency)
        if (code == "SAR") return Conversion(amount, fxAvailable = true)
        val rate = cachedRates[code] ?: return Conversion(amount, fxAvailable = false)
        return Conversion(amount * rate, fxAvailable = true)
    }

    data class Conversion(val amountSar: Double, val fxAvailable: Boolean)

    fun canonicalize(currency: String): String {
        val upper = currency.uppercase()
        return if (upper == "SR") "SAR" else upper
    }

    private suspend fun fetchLiveRates(): Map<String, Double> = withContext(Dispatchers.IO) {
        // One request pulls every currency we might see against SAR
        // as the base — the response is keyed by ISO code → rate, and
        // the inverse (rate per 1 unit of currency in SAR) is just
        // 1 / value since frankfurter uses `from` as the base.
        val url = "https://api.frankfurter.app/latest?from=SAR&to=USD,EUR,GBP,AED,KWD,BHD,QAR,OMR,EGP,JOD"
        val request = Request.Builder().url(url).get().build()
        runCatching {
            http.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    Timber.w("frankfurter HTTP ${response.code}")
                    return@use emptyMap<String, Double>()
                }
                val body = response.body?.string().orEmpty()
                parseFrankfurterResponse(body)
            }
        }.getOrElse {
            Timber.w(it, "frankfurter fetch failed — using static fallback")
            emptyMap()
        }
    }

    internal fun parseFrankfurterResponse(json: String): Map<String, Double> {
        val root = runCatching { JSONObject(json) }.getOrNull() ?: return emptyMap()
        val rates = root.optJSONObject("rates") ?: return emptyMap()
        val out = mutableMapOf<String, Double>()
        val keys = rates.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            val perSar = rates.optDouble(key, 0.0)
            if (perSar > 0) {
                // Response is "units of <key> per 1 SAR"; we want
                // "SAR per 1 unit of <key>" so invert.
                out[key.uppercase()] = 1.0 / perSar
            }
        }
        // SAR is always unity.
        out["SAR"] = 1.0
        return out
    }

    companion object {
        // Re-fetch at most once per 24 hours — ECB publishes daily.
        private const val REFRESH_MILLIS: Long = 24L * 60 * 60 * 1000

        // SAMA-pegged USD/SAR at 3.75 plus a small snapshot for the
        // other currencies that have appeared in real SMS history.
        // These are only used when the live fetch fails.
        val STATIC_RATES: Map<String, Double> = mapOf(
            "SAR" to 1.0,
            "USD" to 3.75,
            "EUR" to 4.08,
            "GBP" to 4.85,
            "AED" to 1.02,
            "KWD" to 12.25,
            "BHD" to 9.95,
            "QAR" to 1.03,
            "OMR" to 9.75,
            "EGP" to 0.076,
            "JOD" to 5.28,
        )
    }
}
