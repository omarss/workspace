package net.omarss.omono.feature.spending

import java.time.Instant
import java.time.ZoneId

data class SpendingTotals(
    val todaySar: Double,
    val monthSar: Double,
    val todayCount: Int,
    val monthCount: Int,
    val monthByCategory: Map<SpendingCategory, Double> = emptyMap(),
) {
    companion object {
        val Empty = SpendingTotals(0.0, 0.0, 0, 0, emptyMap())
    }
}

// Pure totals calculation — exposed at file scope so it can be unit
// tested without any Android / SMS plumbing.
internal fun computeTotals(
    transactions: List<Transaction>,
    now: Instant,
    zone: ZoneId,
): SpendingTotals {
    val zonedNow = now.atZone(zone)
    val startOfDay = zonedNow.toLocalDate().atStartOfDay(zone).toInstant().toEpochMilli()
    val startOfMonth = zonedNow.toLocalDate().withDayOfMonth(1)
        .atStartOfDay(zone).toInstant().toEpochMilli()

    var todaySum = 0.0
    var todayCount = 0
    var monthSum = 0.0
    var monthCount = 0
    val monthByCategory = mutableMapOf<SpendingCategory, Double>()
    for (tx in transactions) {
        if (tx.timestampMillis >= startOfMonth) {
            monthSum += tx.amountSar
            monthCount += 1
            val category = MerchantCategorizer.categorize(tx.merchant)
            monthByCategory.merge(category, tx.amountSar) { a, b -> a + b }
        }
        if (tx.timestampMillis >= startOfDay) {
            todaySum += tx.amountSar
            todayCount += 1
        }
    }
    return SpendingTotals(
        todaySar = todaySum,
        monthSar = monthSum,
        todayCount = todayCount,
        monthCount = monthCount,
        monthByCategory = monthByCategory,
    )
}
