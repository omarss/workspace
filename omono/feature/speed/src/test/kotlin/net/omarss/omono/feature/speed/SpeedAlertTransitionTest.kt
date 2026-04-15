package net.omarss.omono.feature.speed

import io.kotest.matchers.shouldBe
import org.junit.Test

class SpeedAlertTransitionTest {

    @Test
    fun `no limit means no alert`() {
        shouldAlertOnCrossing(previousOverLimit = false, speedKmh = 120f, limitKmh = null) shouldBe false
    }

    @Test
    fun `under the limit does not fire`() {
        shouldAlertOnCrossing(previousOverLimit = false, speedKmh = 50f, limitKmh = 60f) shouldBe false
    }

    @Test
    fun `at exactly the limit does not fire`() {
        shouldAlertOnCrossing(previousOverLimit = false, speedKmh = 60f, limitKmh = 60f) shouldBe false
    }

    @Test
    fun `rising edge fires`() {
        shouldAlertOnCrossing(previousOverLimit = false, speedKmh = 61f, limitKmh = 60f) shouldBe true
    }

    @Test
    fun `already over the limit does not re-fire`() {
        shouldAlertOnCrossing(previousOverLimit = true, speedKmh = 80f, limitKmh = 60f) shouldBe false
    }

    @Test
    fun `dropping back under the limit does not fire`() {
        shouldAlertOnCrossing(previousOverLimit = true, speedKmh = 55f, limitKmh = 60f) shouldBe false
    }

    @Test
    fun `re-crossing after dropping under fires again`() {
        shouldAlertOnCrossing(previousOverLimit = false, speedKmh = 62f, limitKmh = 60f) shouldBe true
    }
}
