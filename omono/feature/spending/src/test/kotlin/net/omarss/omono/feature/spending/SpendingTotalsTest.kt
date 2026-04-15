package net.omarss.omono.feature.spending

import io.kotest.matchers.shouldBe
import org.junit.Test
import java.time.Instant
import java.time.ZoneId

class SpendingTotalsTest {

    // Fix the "now" to a deterministic point so the windows are stable.
    // 2026-04-15T12:00:00 in Asia/Riyadh.
    private val zone = ZoneId.of("Asia/Riyadh")
    private val now: Instant = Instant.parse("2026-04-15T09:00:00Z")
    private val startOfDayMillis = Instant.parse("2026-04-14T21:00:00Z").toEpochMilli() // midnight local
    private val startOfMonthMillis = Instant.parse("2026-03-31T21:00:00Z").toEpochMilli() // 1st 00:00 local

    private fun tx(amount: Double, at: Long): Transaction =
        Transaction(
            amountSar = amount,
            timestampMillis = at,
            bank = Transaction.Bank.AL_RAJHI,
            kind = Transaction.Kind.POS,
            merchant = null,
        )

    @Test
    fun `empty list returns zero totals`() {
        val totals = computeTotals(emptyList(), now, zone)
        totals shouldBe SpendingTotals.Empty
    }

    @Test
    fun `today transactions are in both today and month totals`() {
        val totals = computeTotals(
            listOf(tx(15.0, startOfDayMillis + 60_000)),
            now,
            zone,
        )
        totals.todaySar shouldBe 15.0
        totals.monthSar shouldBe 15.0
        totals.todayCount shouldBe 1
        totals.monthCount shouldBe 1
    }

    @Test
    fun `yesterday transactions count for month but not today`() {
        val totals = computeTotals(
            listOf(tx(50.0, startOfDayMillis - 60_000)),
            now,
            zone,
        )
        totals.todaySar shouldBe 0.0
        totals.monthSar shouldBe 50.0
    }

    @Test
    fun `last month transactions count for neither`() {
        val totals = computeTotals(
            listOf(tx(100.0, startOfMonthMillis - 60_000)),
            now,
            zone,
        )
        totals.todaySar shouldBe 0.0
        totals.monthSar shouldBe 0.0
    }

    @Test
    fun `mixed range sums correctly`() {
        val totals = computeTotals(
            listOf(
                tx(10.0, startOfDayMillis + 1_000),        // today
                tx(20.0, startOfDayMillis + 2_000),        // today
                tx(30.0, startOfDayMillis - 1_000),        // yesterday
                tx(40.0, startOfMonthMillis + 1_000),      // this month
                tx(999.0, startOfMonthMillis - 1_000),     // last month
            ),
            now,
            zone,
        )
        totals.todaySar shouldBe 30.0
        totals.todayCount shouldBe 2
        totals.monthSar shouldBe 100.0
        totals.monthCount shouldBe 4
    }
}
