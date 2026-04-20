package net.omarss.omono.feature.spending

import java.time.Instant
import java.time.YearMonth
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
    // Outgoing transfer totals — money sent to other people /
    // accounts. Kept separate from purchases so salary remittances
    // don't inflate the spending headline.
    val monthTransfersSar: Double = 0.0,
    val monthTransfersCount: Int = 0,
    // Incoming transfer totals — credit transfers, deposits, salary
    // wires. Surfaced on the Transfers card alongside outgoing so
    // the user can see both directions without the headline
    // purchase total being affected by either.
    val monthTransfersInSar: Double = 0.0,
    val monthTransfersInCount: Int = 0,
    // Refund totals — money reversed back into the account. Tracked
    // alongside purchases so the UI can show net spending without
    // polluting the per-category breakdown.
    val monthRefundsSar: Double = 0.0,
    val monthRefundsCount: Int = 0,
    // Benchmarks used to drive the pace indicators on the dashboard.
    //   lastMonthToDateSar — purchases from last month's 1st through the
    //     same day-of-month as today (capped at last month's length).
    //     Compared against monthSar to answer "am I spending more than I
    //     was at this point last month?".
    //   dailyAverageSar    — average daily purchase spend over the 30
    //     days before today. Compared against todaySar to answer "is
    //     today a heavier spending day than usual?".
    // Both are 0 when there isn't enough history to be meaningful; the
    // UI treats 0 as "no benchmark yet".
    val lastMonthToDateSar: Double = 0.0,
    val dailyAverageSar: Double = 0.0,
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
            monthTransfersInSar = 0.0,
            monthTransfersInCount = 0,
            monthRefundsSar = 0.0,
            monthRefundsCount = 0,
            lastMonthToDateSar = 0.0,
            dailyAverageSar = 0.0,
        )
    }
}

// Pure totals calculation — exposed at file scope so it can be unit
// tested without any Android / SMS plumbing. `overrides` lets callers
// inject the user-taught merchant-to-category map so tap-to-correct
// results flow through every aggregation path.
fun computeTotals(
    transactions: List<Transaction>,
    now: Instant,
    zone: ZoneId,
    overrides: Map<String, SpendingCategory> = emptyMap(),
): SpendingTotals {
    val zonedNow = now.atZone(zone)
    val today = zonedNow.toLocalDate()
    val startOfDay = today.atStartOfDay(zone).toInstant().toEpochMilli()
    val startOfMonth = today.withDayOfMonth(1).atStartOfDay(zone).toInstant().toEpochMilli()

    // Last month [1st 00:00 .. same-day-of-month-as-today end of day].
    // If last month has fewer days than today's day-of-month (e.g. today
    // is May 31, last month is April with 30 days), cap at last month's
    // length so we compare an equally-long window.
    val lastMonthFirst = today.minusMonths(1).withDayOfMonth(1)
    val lastMonthDayCap = minOf(today.dayOfMonth, lastMonthFirst.lengthOfMonth())
    val lastMonthThrough = lastMonthFirst.withDayOfMonth(lastMonthDayCap)
    val lastMonthStartMs = lastMonthFirst.atStartOfDay(zone).toInstant().toEpochMilli()
    val lastMonthEndExclusiveMs = lastMonthThrough.plusDays(1)
        .atStartOfDay(zone).toInstant().toEpochMilli()

    // Rolling 30-day window ending at the start of today (today excluded
    // so it can be compared to the average, not be folded into it).
    val rollingStartMs = today.minusDays(30).atStartOfDay(zone).toInstant().toEpochMilli()
    val rollingEndExclusiveMs = startOfDay

    var todaySum = 0.0
    var todayCount = 0
    var monthSum = 0.0
    var monthCount = 0
    var monthTransferSum = 0.0
    var monthTransferCount = 0
    var monthTransferInSum = 0.0
    var monthTransferInCount = 0
    var monthRefundSum = 0.0
    var monthRefundCount = 0
    var lastMonthToDateSum = 0.0
    var rolling30Sum = 0.0
    val monthByCategory = mutableMapOf<SpendingCategory, Double>()
    for (tx in transactions) {
        val ts = tx.timestampMillis
        val inMonth = ts >= startOfMonth
        val inDay = ts >= startOfDay

        if (tx.kind.isPurchase) {
            if (ts in lastMonthStartMs until lastMonthEndExclusiveMs) {
                lastMonthToDateSum += tx.amountSar
            }
            if (ts in rollingStartMs until rollingEndExclusiveMs) {
                rolling30Sum += tx.amountSar
            }
            if (inMonth) {
                monthSum += tx.amountSar
                monthCount += 1
                val category = MerchantCategorizer.categorize(tx.merchant, overrides)
                monthByCategory.merge(category, tx.amountSar) { a, b -> a + b }
                if (inDay) {
                    todaySum += tx.amountSar
                    todayCount += 1
                }
            }
        } else if (tx.kind == Transaction.Kind.REFUND) {
            if (inMonth) {
                monthRefundSum += tx.amountSar
                monthRefundCount += 1
            }
        } else if (tx.kind == Transaction.Kind.TRANSFER_IN) {
            if (inMonth) {
                monthTransferInSum += tx.amountSar
                monthTransferInCount += 1
            }
        } else if (inMonth) {
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
        monthTransfersInSar = monthTransferInSum,
        monthTransfersInCount = monthTransferInCount,
        monthRefundsSar = monthRefundSum,
        monthRefundsCount = monthRefundCount,
        lastMonthToDateSar = lastMonthToDateSum,
        dailyAverageSar = rolling30Sum / 30.0,
    )
}

// Aggregates purchases / transfers / refunds across every transaction
// in the list, without any date scoping. Used for the "All time"
// dashboard tab — the today-scoped and pace fields don't apply so we
// leave them at zero (the UI hides the pace pill for this view). The
// `monthSar` field is reused as the grand-total lifetime spend so the
// UI doesn't need a parallel set of fields.
fun computeTotalsAllTime(
    transactions: List<Transaction>,
    overrides: Map<String, SpendingCategory> = emptyMap(),
): SpendingTotals {
    var purchaseSum = 0.0
    var purchaseCount = 0
    var transferSum = 0.0
    var transferCount = 0
    var transferInSum = 0.0
    var transferInCount = 0
    var refundSum = 0.0
    var refundCount = 0
    val byCategory = mutableMapOf<SpendingCategory, Double>()
    for (tx in transactions) {
        when {
            tx.kind.isPurchase -> {
                purchaseSum += tx.amountSar
                purchaseCount += 1
                val category = MerchantCategorizer.categorize(tx.merchant, overrides)
                byCategory.merge(category, tx.amountSar) { a, b -> a + b }
            }
            tx.kind == Transaction.Kind.REFUND -> {
                refundSum += tx.amountSar
                refundCount += 1
            }
            tx.kind == Transaction.Kind.TRANSFER_IN -> {
                transferInSum += tx.amountSar
                transferInCount += 1
            }
            else -> {
                transferSum += tx.amountSar
                transferCount += 1
            }
        }
    }
    return SpendingTotals(
        todaySar = 0.0,
        monthSar = purchaseSum,
        todayCount = 0,
        monthCount = purchaseCount,
        monthByCategory = byCategory,
        monthTransfersSar = transferSum,
        monthTransfersCount = transferCount,
        monthTransfersInSar = transferInSum,
        monthTransfersInCount = transferInCount,
        monthRefundsSar = refundSum,
        monthRefundsCount = refundCount,
        lastMonthToDateSar = 0.0,
        dailyAverageSar = 0.0,
    )
}

// Aggregates purchases / transfers / refunds for an arbitrary calendar
// month. The today-scoped and pace-benchmark fields don't apply to
// historic months, so this variant leaves them at zero — the UI hides
// the pace pill accordingly.
fun computeTotalsForMonth(
    transactions: List<Transaction>,
    yearMonth: YearMonth,
    zone: ZoneId,
    overrides: Map<String, SpendingCategory> = emptyMap(),
): SpendingTotals {
    val startOfMonth = yearMonth.atDay(1).atStartOfDay(zone).toInstant().toEpochMilli()
    val endExclusive = yearMonth.plusMonths(1).atDay(1)
        .atStartOfDay(zone).toInstant().toEpochMilli()

    var monthSum = 0.0
    var monthCount = 0
    var monthTransferSum = 0.0
    var monthTransferCount = 0
    var monthTransferInSum = 0.0
    var monthTransferInCount = 0
    var monthRefundSum = 0.0
    var monthRefundCount = 0
    val monthByCategory = mutableMapOf<SpendingCategory, Double>()
    for (tx in transactions) {
        if (tx.timestampMillis !in startOfMonth until endExclusive) continue
        when {
            tx.kind.isPurchase -> {
                monthSum += tx.amountSar
                monthCount += 1
                val category = MerchantCategorizer.categorize(tx.merchant, overrides)
                monthByCategory.merge(category, tx.amountSar) { a, b -> a + b }
            }
            tx.kind == Transaction.Kind.REFUND -> {
                monthRefundSum += tx.amountSar
                monthRefundCount += 1
            }
            tx.kind == Transaction.Kind.TRANSFER_IN -> {
                monthTransferInSum += tx.amountSar
                monthTransferInCount += 1
            }
            else -> {
                monthTransferSum += tx.amountSar
                monthTransferCount += 1
            }
        }
    }
    return SpendingTotals(
        todaySar = 0.0,
        monthSar = monthSum,
        todayCount = 0,
        monthCount = monthCount,
        monthByCategory = monthByCategory,
        monthTransfersSar = monthTransferSum,
        monthTransfersCount = monthTransferCount,
        monthTransfersInSar = monthTransferInSum,
        monthTransfersInCount = monthTransferInCount,
        monthRefundsSar = monthRefundSum,
        monthRefundsCount = monthRefundCount,
        lastMonthToDateSar = 0.0,
        dailyAverageSar = 0.0,
    )
}
