package net.omarss.omono.feature.spending

import io.kotest.matchers.doubles.shouldBeWithinPercentageOf
import io.kotest.matchers.shouldBe
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class CurrencyConverterTest {

    private val converter = CurrencyConverter()

    @Test
    fun `static fallback uses SAMA peg for USD`() {
        // 1 USD = 3.75 SAR under the SAMA peg. This is what we fall
        // back to when the live fetch hasn't happened yet.
        converter.toSar(230.0, "USD") shouldBe 230.0 * 3.75
    }

    @Test
    fun `SR abbreviation is treated as SAR`() {
        converter.toSar(100.0, "SR") shouldBe 100.0
    }

    @Test
    fun `unknown currency returns the amount unchanged`() {
        // "XYZ" isn't in the fallback table — we'd rather under-count
        // than silently drop the row.
        converter.toSar(500.0, "XYZ") shouldBe 500.0
    }

    @Test
    fun `parses frankfurter response and bridges via SAMA peg`() {
        // Frankfurter now bases on USD (SAR is no longer in their
        // published set). Response shape: "1 USD = rates[X] units of X".
        // We want SAR per unit of X = (1 / rates[X]) × 3.75.
        //
        //   EUR: 1 USD = 0.847 EUR  → 1 EUR ≈ 1.181 USD ≈ 4.43 SAR
        //   GBP: 1 USD = 0.739 GBP  → 1 GBP ≈ 1.353 USD ≈ 5.07 SAR
        val json = """
            {
              "amount": 1.0,
              "base": "USD",
              "date": "2026-04-17",
              "rates": {
                "EUR": 0.847,
                "GBP": 0.739
              }
            }
        """.trimIndent()
        val rates = converter.parseFrankfurterResponse(json)
        rates["EUR"]!!.shouldBeWithinPercentageOf(4.43, 1.0)
        rates["GBP"]!!.shouldBeWithinPercentageOf(5.07, 1.0)
        rates["USD"] shouldBe 3.75
        rates["SAR"] shouldBe 1.0
    }

    @Test
    fun `empty json yields empty map`() {
        converter.parseFrankfurterResponse("") shouldBe emptyMap()
    }
}
