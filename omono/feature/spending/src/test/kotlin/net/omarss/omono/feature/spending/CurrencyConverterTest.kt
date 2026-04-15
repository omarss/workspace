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
    fun `parses frankfurter response and inverts rates`() {
        // Frankfurter returns "units of currency per 1 SAR". We need
        // "SAR per 1 unit", so 1 USD at 0.2667 per SAR → 3.75 SAR.
        val json = """
            {
              "amount": 1.0,
              "base": "SAR",
              "date": "2026-04-15",
              "rates": {
                "USD": 0.2667,
                "EUR": 0.245
              }
            }
        """.trimIndent()
        val rates = converter.parseFrankfurterResponse(json)
        rates["USD"]!!.shouldBeWithinPercentageOf(3.75, 0.5)
        rates["EUR"]!!.shouldBeWithinPercentageOf(4.08, 1.0)
        rates["SAR"] shouldBe 1.0
    }

    @Test
    fun `empty json yields empty map`() {
        converter.parseFrankfurterResponse("") shouldBe emptyMap()
    }
}
