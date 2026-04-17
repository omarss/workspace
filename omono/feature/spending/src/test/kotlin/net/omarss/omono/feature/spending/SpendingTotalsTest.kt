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

    // Last month window endpoints for the fixed "now" (Apr 15, Asia/Riyadh).
    // Last month = March 2026; day cap = 15 (Mar has 31 days, no cap).
    private val lastMonthStartMillis = Instant.parse("2026-02-28T21:00:00Z").toEpochMilli() // Mar 1 00:00 local
    private val lastMonthEndMillis = Instant.parse("2026-03-15T21:00:00Z").toEpochMilli()   // Mar 16 00:00 local (exclusive)
    // Rolling 30-day window: Mar 16 00:00 local .. Apr 15 00:00 local.
    private val rollingStartMillis = Instant.parse("2026-03-15T21:00:00Z").toEpochMilli()   // Mar 16 00:00 local

    private fun tx(amount: Double, at: Long, merchant: String? = null): Transaction =
        Transaction(
            amountSar = amount,
            timestampMillis = at,
            bank = Transaction.Bank.AL_RAJHI,
            kind = Transaction.Kind.POS,
            merchant = merchant,
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

    @Test
    fun `last month to date sums purchases in the matching window`() {
        val totals = computeTotals(
            listOf(
                tx(70.0, lastMonthStartMillis + 60_000),     // Mar 1, included
                tx(90.0, lastMonthEndMillis - 60_000),       // Mar 15, included (before exclusive end)
                tx(40.0, lastMonthEndMillis + 60_000),       // Mar 16, excluded (past the cap)
                tx(25.0, lastMonthStartMillis - 60_000),     // Feb 28, excluded (before window)
            ),
            now,
            zone,
        )
        totals.lastMonthToDateSar shouldBe 160.0
    }

    @Test
    fun `daily average divides past 30 days by 30 and excludes today`() {
        val totals = computeTotals(
            listOf(
                tx(300.0, rollingStartMillis + 60_000),      // inside 30-day window
                tx(150.0, startOfDayMillis - 60_000),        // yesterday, inside window
                tx(50.0, startOfDayMillis + 60_000),         // today, must NOT inflate average
                tx(9999.0, rollingStartMillis - 60_000),     // before window, excluded
            ),
            now,
            zone,
        )
        // (300 + 150) / 30 = 15.0
        totals.dailyAverageSar shouldBe 15.0
        // Today purchase still reflected in todaySar but not in the average.
        totals.todaySar shouldBe 50.0
    }

    @Test
    fun `transfers do not contribute to either benchmark`() {
        val transfer = Transaction(
            amountSar = 5000.0,
            timestampMillis = lastMonthStartMillis + 60_000,
            bank = Transaction.Bank.AL_RAJHI,
            kind = Transaction.Kind.TRANSFER_OUT,
            merchant = "Salary remittance",
        )
        val totals = computeTotals(listOf(transfer), now, zone)
        totals.lastMonthToDateSar shouldBe 0.0
        totals.dailyAverageSar shouldBe 0.0
    }

    @Test
    fun `category totals aggregate within the month window`() {
        val totals = computeTotals(
            listOf(
                tx(50.0, startOfMonthMillis + 1_000, merchant = "Jahez"),
                tx(80.0, startOfMonthMillis + 2_000, merchant = "Jahez"),
                tx(120.0, startOfMonthMillis + 3_000, merchant = "ALDREES 4"),
                tx(200.0, startOfMonthMillis + 4_000, merchant = "Ninja Retail Company"),
                tx(999.0, startOfMonthMillis - 1_000, merchant = "Jahez"), // last month
            ),
            now,
            zone,
        )
        totals.monthByCategory[SpendingCategory.FOOD] shouldBe 130.0
        totals.monthByCategory[SpendingCategory.FUEL] shouldBe 120.0
        totals.monthByCategory[SpendingCategory.GROCERIES] shouldBe 200.0
    }
}
