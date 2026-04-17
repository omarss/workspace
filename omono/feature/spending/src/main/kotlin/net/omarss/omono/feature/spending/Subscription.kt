package net.omarss.omono.feature.spending

import kotlin.math.abs

// A merchant the user appears to be paying on a monthly cadence.
// `amountSar` is the mean across detected charges (covers FX drift on
// USD-denominated services — Claude 230 USD @ 3.75 ≠ same SAR every
// month, but the mean is what the user mentally expects).
//
// `nextRenewalAtMillis` is a forward projection: `lastChargedAtMillis`
// plus the median observed interval. Not guaranteed — just "if the
// pattern holds, expect a charge around this date".
data class Subscription(
    val merchant: String,
    val amountSar: Double,
    val lastChargedAtMillis: Long,
    val nextRenewalAtMillis: Long,
    val cadenceDays: Int,
    val chargeCount: Int,
)

// Scans the transaction cache for recurring-merchant-and-amount
// patterns. Designed to be called over the 180-day window the
// repository keeps in memory — two months of history is the minimum
// to detect anything, six months makes the pattern obvious.
//
// v1 intentionally narrow:
//   * monthly cadence only (25–35 day intervals, lenient around 28/30/31)
//   * fixed amount (±5% of the group's median to absorb FX drift)
//   * purchases only (transfers, refunds, CC echoes already excluded)
//
// Variable-amount recurring charges like utilities don't get detected
// — their bills are already surfaced in the dedicated Bills card.
fun detectSubscriptions(
    transactions: List<Transaction>,
    nowMillis: Long = System.currentTimeMillis(),
): List<Subscription> {
    val purchases = transactions
        .filter { it.kind.isPurchase }
        .filter { !it.merchant.isNullOrBlank() }

    return purchases
        .groupBy { normalizeMerchant(it.merchant!!) }
        .mapNotNull { (merchantKey, txs) ->
            if (txs.size < MIN_CHARGES) return@mapNotNull null

            // Keep only the charges that cluster around the median
            // amount — filters out one-off big spends from an
            // otherwise-subscription-looking merchant (e.g. the user
            // buys a lunch AND has a subscription at the same place).
            val medianAmount = txs.map { it.amountSar }.median()
            val tolerance = medianAmount * AMOUNT_TOLERANCE
            val cluster = txs.filter { abs(it.amountSar - medianAmount) <= tolerance }
            if (cluster.size < MIN_CHARGES) return@mapNotNull null

            val sorted = cluster.sortedBy { it.timestampMillis }
            val intervals = sorted.zipWithNext { a, b ->
                ((b.timestampMillis - a.timestampMillis) / MILLIS_PER_DAY).toInt()
            }
            val medianInterval = intervals.median().toInt()
            if (medianInterval !in MIN_CADENCE_DAYS..MAX_CADENCE_DAYS) {
                return@mapNotNull null
            }

            val last = sorted.last()
            val cadenceMillis = medianInterval.toLong() * MILLIS_PER_DAY
            // If the pattern is still alive but we haven't seen the
            // newest charge yet, the naive projection can be a few
            // days in the past — roll it forward one full cadence so
            // the UI reads "renews in N days" instead of a bogus
            // negative. When the gap is larger than half a cadence
            // (~15 days for a monthly charge), treat the subscription
            // as dead and drop it from the list.
            val rawNextRenewal = last.timestampMillis + cadenceMillis
            val gracePastDue = cadenceMillis / 2
            if (nowMillis - rawNextRenewal > gracePastDue) return@mapNotNull null
            val nextRenewal = if (rawNextRenewal < nowMillis) {
                rawNextRenewal + cadenceMillis
            } else {
                rawNextRenewal
            }

            Subscription(
                merchant = merchantKey,
                amountSar = cluster.map { it.amountSar }.average(),
                lastChargedAtMillis = last.timestampMillis,
                nextRenewalAtMillis = nextRenewal,
                cadenceDays = medianInterval,
                chargeCount = cluster.size,
            )
        }
        .sortedBy { it.nextRenewalAtMillis }
}

// Light normalization so different-case / padded-whitespace merchant
// strings ("Jahez" / "jahez" / "Jahez  ") collapse into one group.
// Deliberately conservative — aggressive normalization (e.g. stripping
// trailing "*code" suffixes on Al Rajhi's "GOOGLE*NO" shape) would
// risk merging unrelated Google charges; users can re-request if that
// bites.
internal fun normalizeMerchant(raw: String): String = raw
    .trim()
    .lowercase()
    .replace(WHITESPACE_RE, " ")

private val WHITESPACE_RE = Regex("\\s+")

// Classic middle-value median. For even-sized inputs we take the
// lower of the two middles — slight downward bias but deterministic
// and matches the "pick an observed value" intuition.
private fun List<Double>.median(): Double {
    val sorted = sorted()
    return sorted[sorted.size / 2]
}

@JvmName("medianInt")
private fun List<Int>.median(): Int {
    val sorted = sorted()
    return sorted[sorted.size / 2]
}

private const val MIN_CHARGES = 2
private const val AMOUNT_TOLERANCE = 0.05     // ±5 %
private const val MIN_CADENCE_DAYS = 25
private const val MAX_CADENCE_DAYS = 35
private const val MILLIS_PER_DAY = 24L * 60 * 60 * 1000
