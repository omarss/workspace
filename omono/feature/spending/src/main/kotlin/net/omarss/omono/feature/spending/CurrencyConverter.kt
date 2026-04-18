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

// Converts foreign-currency transaction amounts into SAR. Tries
// frankfurter.dev (free ECB reference rates, no auth, no card) first.
// SAR isn't in Frankfurter's supported-currencies list any more, so
// we query with USD as the base and bridge via the SAMA peg (1 USD =
// 3.75 SAR, stable since 1986) to derive SAR-per-unit for every code.
// On network failure or for codes Frankfurter no longer publishes
// (AED, KWD, BHD, QAR, OMR, EGP, JOD — mostly regional) we fall back
// to a small static snapshot carried in-memory.
//
// Rates are fetched lazily on first use and cached for REFRESH_MILLIS
// so we don't hit the network on every transaction parse.
//
// History: this used to target `api.frankfurter.app`, which now 301
// redirects to `api.frankfurter.dev/v1/...`. OkHttp doesn't follow
// cross-host redirects by default without enabling it, so the old URL
// surfaced as `frankfurter HTTP 404` in the diagnostics log on every
// feature start. Direct URL is cheaper than the redirect either way.
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
        // USD as the base because Frankfurter dropped SAR (and the
        // rest of the Gulf) from its published currency set. SAR
        // rides on the USD peg at 3.75, so we can derive SAR-per-X
        // from USD-per-X without a round trip.
        val url = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=EUR,GBP,JPY,CAD,AUD,CHF,CNY,INR,SGD,HKD"
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

    // Frankfurter response shape: `{"base":"USD","rates":{"EUR":0.847,...}}`,
    // meaning "1 USD = <rate> <key>". We want "SAR per 1 unit of <key>",
    // which is `(1 / rate) × SAR_PER_USD`. USD itself is always
    // `SAR_PER_USD` (the SAMA peg); we add it to the map even though
    // Frankfurter doesn't echo the base in `rates`.
    internal fun parseFrankfurterResponse(json: String): Map<String, Double> {
        val root = runCatching { JSONObject(json) }.getOrNull() ?: return emptyMap()
        val rates = root.optJSONObject("rates") ?: return emptyMap()
        val out = mutableMapOf<String, Double>()
        val keys = rates.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            val perUsd = rates.optDouble(key, 0.0)
            if (perUsd > 0) {
                // (SAR per unit of X) = (USD per unit of X) × (SAR per USD)
                //                     = (1 / perUsd) × SAR_PER_USD.
                out[key.uppercase()] = SAR_PER_USD / perUsd
            }
        }
        out["USD"] = SAR_PER_USD
        out["SAR"] = 1.0
        return out
    }

    companion object {
        // Re-fetch at most once per 24 hours — ECB publishes daily.
        private const val REFRESH_MILLIS: Long = 24L * 60 * 60 * 1000

        // SAMA peg: 1 USD = 3.75 SAR. Hard-pegged since 1986 and
        // re-confirmed every year; used as the bridge to every code
        // Frankfurter returns (it bases on USD now) and as the SAR
        // fallback rate for any currency the live feed misses.
        internal const val SAR_PER_USD: Double = 3.75

        // Static snapshot for codes Frankfurter no longer publishes
        // (GCC + EGP + JOD) plus USD/EUR/GBP as a safe fallback if
        // the network is down. Stale quotes are better than an empty
        // cache that causes every foreign-currency transaction to
        // fall through to the "FX unavailable" badge.
        val STATIC_RATES: Map<String, Double> = mapOf(
            "SAR" to 1.0,
            "USD" to SAR_PER_USD,
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
