package net.omarss.omono.feature.spending

import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.shouldBe
import org.junit.Test

class SubscriptionDetectorTest {

    // Fix "now" to a stable post-charge moment so next-renewal
    // projections don't trip over real clock.
    private val nowMillis: Long = dateMillis("2026-04-17")

    @Test
    fun `two monthly charges at the same amount are detected`() {
        val txs = listOf(
            pos("Jahez", 50.0, "2026-03-17"),
            pos("Jahez", 50.0, "2026-02-17"),
        )
        val subs = detectSubscriptions(txs, nowMillis)
        subs shouldHaveSize 1
        val sub = subs.first()
        sub.merchant shouldBe "jahez"
        sub.amountSar shouldBe 50.0
        sub.cadenceDays shouldBe 28
        sub.chargeCount shouldBe 2
        sub.lastChargedAtMillis shouldBe dateMillis("2026-03-17")
        // Naive projection (last + 28d) lands on 2026-04-14, which is
        // 3 days before "now" — inside the half-cadence grace window,
        // so the detector rolls it forward one cadence to 2026-05-12
        // so the UI shows a positive "renews in N days".
        sub.nextRenewalAtMillis shouldBe dateMillis("2026-05-12")
    }

    @Test
    fun `single charge is not a subscription`() {
        val txs = listOf(pos("Jahez", 50.0, "2026-03-17"))
        detectSubscriptions(txs, nowMillis) shouldHaveSize 0
    }

    @Test
    fun `claude monthly in USD-drift SAR still clusters within 5 percent`() {
        // Claude is billed in USD; the FX-converted SAR drifts month-on-month.
        // 862.50 and 867.10 are ~0.5% apart — must stay in one cluster.
        val txs = listOf(
            pos("CLAUDE", 862.50, "2026-02-01"),
            pos("CLAUDE", 867.10, "2026-03-01"),
            pos("CLAUDE", 862.75, "2026-04-01"),
        )
        val subs = detectSubscriptions(txs, nowMillis)
        subs shouldHaveSize 1
        subs.first().chargeCount shouldBe 3
    }

    @Test
    fun `variable amount merchant is not a subscription`() {
        // Same merchant hit three times at wildly different amounts —
        // outside the 5% tolerance around the median, so no cluster.
        val txs = listOf(
            pos("Jahez", 50.0, "2026-02-17"),
            pos("Jahez", 200.0, "2026-03-17"),
            pos("Jahez", 25.0, "2026-04-15"),
        )
        detectSubscriptions(txs, nowMillis) shouldHaveSize 0
    }

    @Test
    fun `weekly cadence is rejected as too fast for monthly detector`() {
        val txs = listOf(
            pos("Coffee Bar", 15.0, "2026-04-01"),
            pos("Coffee Bar", 15.0, "2026-04-08"),
            pos("Coffee Bar", 15.0, "2026-04-15"),
        )
        detectSubscriptions(txs, nowMillis) shouldHaveSize 0
    }

    @Test
    fun `yearly cadence is rejected as too slow for monthly detector`() {
        val txs = listOf(
            pos("Annual Fee", 500.0, "2025-04-01"),
            pos("Annual Fee", 500.0, "2026-04-01"),
        )
        detectSubscriptions(txs, nowMillis) shouldHaveSize 0
    }

    @Test
    fun `projected next renewal already in the past is suppressed`() {
        // Pattern stops — last charge 60 days before "now" and the
        // median interval is 30 days, so the predicted next is in the
        // past. Don't confuse the user with a stale prediction.
        val txs = listOf(
            pos("Gone", 40.0, "2025-12-17"),
            pos("Gone", 40.0, "2026-01-17"),
            pos("Gone", 40.0, "2026-02-17"),
        )
        detectSubscriptions(txs, nowMillis) shouldHaveSize 0
    }

    @Test
    fun `sorts output by next-renewal ascending`() {
        val txs = listOf(
            pos("B Later", 10.0, "2026-03-05"),
            pos("B Later", 10.0, "2026-04-05"),
            pos("A Sooner", 20.0, "2026-03-01"),
            pos("A Sooner", 20.0, "2026-04-01"),
        )
        val subs = detectSubscriptions(txs, nowMillis)
        subs shouldHaveSize 2
        subs[0].merchant shouldBe "a sooner"
        subs[1].merchant shouldBe "b later"
    }

    @Test
    fun `transfers and refunds never count as subscriptions`() {
        // Two TRANSFER_OUTs to the same person at the same amount one
        // month apart is not a "subscription" — it's a standing order
        // the user already sees in the Transfers card.
        val txs = listOf(
            tx(Transaction.Kind.TRANSFER_OUT, "Mom", 500.0, "2026-03-01"),
            tx(Transaction.Kind.TRANSFER_OUT, "Mom", 500.0, "2026-04-01"),
            tx(Transaction.Kind.REFUND, "ATM", 20.0, "2026-03-15"),
            tx(Transaction.Kind.REFUND, "ATM", 20.0, "2026-04-15"),
        )
        detectSubscriptions(txs, nowMillis) shouldHaveSize 0
    }

    @Test
    fun `merchant casing and padding collapse into one group`() {
        val txs = listOf(
            pos("JAHEZ", 50.0, "2026-02-17"),
            pos("  jahez ", 50.0, "2026-03-17"),
        )
        val subs = detectSubscriptions(txs, nowMillis)
        subs shouldHaveSize 1
        subs.first().merchant shouldBe "jahez"
    }

    // --- fixtures ---------------------------------------------------

    private fun pos(merchant: String, amount: Double, date: String): Transaction =
        tx(Transaction.Kind.POS, merchant, amount, date)

    private fun tx(
        kind: Transaction.Kind,
        merchant: String,
        amount: Double,
        date: String,
    ): Transaction = Transaction(
        amountSar = amount,
        timestampMillis = dateMillis(date),
        bank = Transaction.Bank.AL_RAJHI,
        kind = kind,
        merchant = merchant,
    )

    private fun dateMillis(isoDate: String): Long {
        // Midnight local — good enough for day-granularity cadence math.
        val ld = java.time.LocalDate.parse(isoDate)
        return ld.atStartOfDay(java.time.ZoneId.of("Asia/Riyadh"))
            .toInstant().toEpochMilli()
    }
}
