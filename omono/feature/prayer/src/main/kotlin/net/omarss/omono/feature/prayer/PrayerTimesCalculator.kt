package net.omarss.omono.feature.prayer

import com.batoulapps.adhan.CalculationMethod
import com.batoulapps.adhan.Coordinates
import com.batoulapps.adhan.Madhab
import com.batoulapps.adhan.PrayerTimes
import com.batoulapps.adhan.data.DateComponents
import java.time.LocalDate

// Pure wrapper around the Adhan library — takes a place, a date, and
// a settings snapshot and returns the day's ordered list of prayer
// times. Kept framework-free (no Android, no Hilt) so the test suite
// can exercise it directly without Robolectric.
//
// Adhan does all the astronomy on-device via the Meeus algorithms —
// no network, no cached tables. That's what gives us the "works
// offline" property the user asked for.
object PrayerTimesCalculator {

    fun computeDay(
        latitude: Double,
        longitude: Double,
        date: LocalDate,
        settings: PrayerSettingsSnapshot = PrayerSettingsSnapshot(),
    ): PrayerDayTimes {
        val params = settings.method.toAdhan().parameters
        params.madhab = settings.madhab.toAdhan()
        val components = DateComponents(date.year, date.monthValue, date.dayOfMonth)
        val coords = Coordinates(latitude, longitude)
        val pt = PrayerTimes(coords, components, params)
        val ordered = listOf(
            PrayerTime(PrayerKind.Fajr, pt.fajr.time),
            PrayerTime(PrayerKind.Sunrise, pt.sunrise.time),
            PrayerTime(PrayerKind.Dhuhr, pt.dhuhr.time),
            PrayerTime(PrayerKind.Asr, pt.asr.time),
            PrayerTime(PrayerKind.Maghrib, pt.maghrib.time),
            PrayerTime(PrayerKind.Isha, pt.isha.time),
        )
        return PrayerDayTimes(date = date, times = ordered)
    }
}

private fun PrayerCalculationMethod.toAdhan(): CalculationMethod = when (this) {
    PrayerCalculationMethod.UmmAlQura -> CalculationMethod.UMM_AL_QURA
    PrayerCalculationMethod.MuslimWorldLeague -> CalculationMethod.MUSLIM_WORLD_LEAGUE
    PrayerCalculationMethod.Egyptian -> CalculationMethod.EGYPTIAN
    PrayerCalculationMethod.Karachi -> CalculationMethod.KARACHI
    PrayerCalculationMethod.Dubai -> CalculationMethod.DUBAI
    PrayerCalculationMethod.Qatar -> CalculationMethod.QATAR
    PrayerCalculationMethod.Kuwait -> CalculationMethod.KUWAIT
    PrayerCalculationMethod.MoonsightingCommittee -> CalculationMethod.MOON_SIGHTING_COMMITTEE
    PrayerCalculationMethod.Singapore -> CalculationMethod.SINGAPORE
    PrayerCalculationMethod.NorthAmerica -> CalculationMethod.NORTH_AMERICA
}

private fun PrayerMadhab.toAdhan(): Madhab = when (this) {
    PrayerMadhab.Shafi -> Madhab.SHAFI
    PrayerMadhab.Hanafi -> Madhab.HANAFI
}
