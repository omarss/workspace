package net.omarss.omono.feature.spending

import java.time.Instant
import java.time.ZoneId

data class SpendingTotals(
    // Purchase totals — consumer spending (PoS, online, bills, MOI,
    // withdrawals, CC payments). These drive the headline "spending"
    // numbers in the UI and notification.
    val todaySar: Double,
    val monthSar: Double,
    val todayCount: Int,
    val monthCount: Int,
    val monthByCategory: Map<SpendingCategory, Double> = emptyMap(),
    // Transfer totals — money sent to other people / accounts. Kept
    // separate so salary remittances don't inflate the spending
    // headline.
    val monthTransfersSar: Double = 0.0,
    val monthTransfersCount: Int = 0,
) {
    companion object {
        val Empty = SpendingTotals(
            todaySar = 0.0,
            monthSar = 0.0,
            todayCount = 0,
            monthCount = 0,
            monthByCategory = emptyMap(),
            monthTransfersSar = 0.0,
            monthTransfersCount = 0,
        )
    }
}

// Pure totals calculation — exposed at file scope so it can be unit
// tested without any Android / SMS plumbing.
fun computeTotals(
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
    var monthTransferSum = 0.0
    var monthTransferCount = 0
    val monthByCategory = mutableMapOf<SpendingCategory, Double>()
    for (tx in transactions) {
        val inMonth = tx.timestampMillis >= startOfMonth
        val inDay = tx.timestampMillis >= startOfDay
        if (!inMonth) continue

        if (tx.kind.isPurchase) {
            monthSum += tx.amountSar
            monthCount += 1
            val category = MerchantCategorizer.categorize(tx.merchant)
            monthByCategory.merge(category, tx.amountSar) { a, b -> a + b }
            if (inDay) {
                todaySum += tx.amountSar
                todayCount += 1
            }
        } else {
            monthTransferSum += tx.amountSar
            monthTransferCount += 1
        }
    }
    return SpendingTotals(
        todaySar = todaySum,
        monthSar = monthSum,
        todayCount = todayCount,
        monthCount = monthCount,
        monthByCategory = monthByCategory,
        monthTransfersSar = monthTransferSum,
        monthTransfersCount = monthTransferCount,
    )
}
