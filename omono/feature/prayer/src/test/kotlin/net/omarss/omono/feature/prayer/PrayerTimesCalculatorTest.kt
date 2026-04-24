package net.omarss.omono.feature.prayer

import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.shouldBe
import org.junit.Test
import java.time.LocalDate

// The Adhan library is deterministic for a given (lat, lon, date,
// method). We don't need to assert wall-clock times to the minute —
// a handful of invariants is enough to catch regressions:
//   * Six entries (Fajr, Sunrise, Dhuhr, Asr, Maghrib, Isha)
//   * Monotonically increasing timestamps
//
// Pinned to Riyadh / Umm al-Qura since that's the project's primary
// use case. If the numbers drift by minutes on a future adhan bump
// that's fine — the invariants still hold.
class PrayerTimesCalculatorTest {

    @Test
    fun `riyadh returns six ordered prayer times`() {
        val day = PrayerTimesCalculator.computeDay(
            latitude = 24.7136,
            longitude = 46.6753,
            date = LocalDate.of(2026, 4, 24),
            settings = PrayerSettingsSnapshot(
                method = PrayerCalculationMethod.UmmAlQura,
                madhab = PrayerMadhab.Shafi,
            ),
        )
        day.times shouldHaveSize 6
        day.times.map { it.kind } shouldBe listOf(
            PrayerKind.Fajr,
            PrayerKind.Sunrise,
            PrayerKind.Dhuhr,
            PrayerKind.Asr,
            PrayerKind.Maghrib,
            PrayerKind.Isha,
        )
        val instants = day.times.map { it.atEpochMs }
        check(instants.zipWithNext().all { (a, b) -> a < b }) {
            "prayer times not monotonically increasing: $instants"
        }
    }

    @Test
    fun `nextAfter returns the next upcoming prayer`() {
        val day = PrayerTimesCalculator.computeDay(
            latitude = 24.7136,
            longitude = 46.6753,
            date = LocalDate.of(2026, 4, 24),
        )
        val asrAt = day.times.first { it.kind == PrayerKind.Asr }.atEpochMs
        // A moment one minute before Asr: the next call should land
        // on Asr itself.
        val windowBefore = asrAt - 60_000L
        day.nextAfter(windowBefore)?.kind shouldBe PrayerKind.Asr
    }

    @Test
    fun `hanafi asr is later than shafi asr`() {
        val shafi = PrayerTimesCalculator.computeDay(
            latitude = 24.7136,
            longitude = 46.6753,
            date = LocalDate.of(2026, 4, 24),
            settings = PrayerSettingsSnapshot(madhab = PrayerMadhab.Shafi),
        ).times.first { it.kind == PrayerKind.Asr }.atEpochMs

        val hanafi = PrayerTimesCalculator.computeDay(
            latitude = 24.7136,
            longitude = 46.6753,
            date = LocalDate.of(2026, 4, 24),
            settings = PrayerSettingsSnapshot(madhab = PrayerMadhab.Hanafi),
        ).times.first { it.kind == PrayerKind.Asr }.atEpochMs

        check(hanafi > shafi) { "hanafi asr should be later than shafi" }
    }
}
