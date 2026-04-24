package net.omarss.omono.feature.prayer

import io.kotest.matchers.shouldBe
import org.junit.Test

// Regression test for the Fajr-only athan rule. Exercises the pure
// `shouldPlayAthan` guard directly so a future refactor that moves
// the check elsewhere can't silently play the athan on other prayers.
class ShouldPlayAthanTest {

    private val enabledDefaults = PrayerSettingsSnapshot(playAthanAtFajr = true)

    @Test
    fun `only fajr plays the athan when enabled`() {
        shouldPlayAthan(PrayerKind.Fajr, enabledDefaults) shouldBe true
        PrayerKind.entries.filter { it != PrayerKind.Fajr }.forEach { kind ->
            shouldPlayAthan(kind, enabledDefaults) shouldBe false
        }
    }

    @Test
    fun `disabling the athan suppresses fajr too`() {
        val disabled = PrayerSettingsSnapshot(playAthanAtFajr = false)
        PrayerKind.entries.forEach { kind ->
            shouldPlayAthan(kind, disabled) shouldBe false
        }
    }
}
