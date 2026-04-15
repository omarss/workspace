package net.omarss.omono.feature.spending

import io.kotest.matchers.shouldBe
import org.junit.Test

class MerchantCategorizerTest {

    @Test
    fun `jahez is food`() {
        MerchantCategorizer.categorize("Jahez") shouldBe SpendingCategory.FOOD
    }

    @Test
    fun `ninja retail is groceries`() {
        MerchantCategorizer.categorize("Ninja Retail Company") shouldBe SpendingCategory.GROCERIES
    }

    @Test
    fun `ninja food is food`() {
        MerchantCategorizer.categorize("Ninja Food Company") shouldBe SpendingCategory.FOOD
    }

    @Test
    fun `aldrees is fuel`() {
        MerchantCategorizer.categorize("ALDREES 4") shouldBe SpendingCategory.FUEL
    }

    @Test
    fun `lulu is groceries`() {
        MerchantCategorizer.categorize("LuLu Hypermarket") shouldBe SpendingCategory.GROCERIES
    }

    @Test
    fun `java time is food`() {
        MerchantCategorizer.categorize("Java Time") shouldBe SpendingCategory.FOOD
    }

    @Test
    fun `stc pay is utilities`() {
        MerchantCategorizer.categorize("STC PAY") shouldBe SpendingCategory.UTILITIES
    }

    @Test
    fun `null is other`() {
        MerchantCategorizer.categorize(null) shouldBe SpendingCategory.OTHER
    }

    @Test
    fun `blank is other`() {
        MerchantCategorizer.categorize("") shouldBe SpendingCategory.OTHER
    }

    @Test
    fun `unknown merchant is other`() {
        MerchantCategorizer.categorize("SM.NORD* C") shouldBe SpendingCategory.OTHER
    }

    @Test
    fun `case insensitive match`() {
        MerchantCategorizer.categorize("JAHEZ") shouldBe SpendingCategory.FOOD
        MerchantCategorizer.categorize("jahez") shouldBe SpendingCategory.FOOD
    }
}
