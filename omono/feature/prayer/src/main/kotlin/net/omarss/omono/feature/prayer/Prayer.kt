package net.omarss.omono.feature.prayer

import java.time.LocalDate

// The five daily prayers + sunrise. Sunrise isn't a prayer in the
// classical sense, but the library exposes it and the UI shows it
// between Fajr and Dhuhr so the user sees when Fajr "ends".
enum class PrayerKind { Fajr, Sunrise, Dhuhr, Asr, Maghrib, Isha }

// Ordered pair for a single prayer — epoch-ms timestamp the alarm
// fires at and the kind so the notification copy can say
// "Fajr" / "Dhuhr". `atEpochMs` is UTC; callers format to the
// device's current time zone.
data class PrayerTime(
    val kind: PrayerKind,
    val atEpochMs: Long,
)

// The full day. Ordered Fajr → Isha (with sunrise after Fajr).
data class PrayerDayTimes(
    val date: LocalDate,
    val times: List<PrayerTime>,
) {
    fun nextAfter(nowEpochMs: Long): PrayerTime? =
        times.firstOrNull { it.atEpochMs > nowEpochMs }

    fun currentOrNull(nowEpochMs: Long): PrayerTime? =
        times.lastOrNull { it.atEpochMs <= nowEpochMs }
}

// Calculation method + madhab. Maps 1:1 onto the adhan enums but
// lives in our domain so ViewModels don't have to pull the library
// namespace into their import blocks. Defaults to Umm al-Qura /
// Shafi'i which matches the project's primary user base (KSA).
enum class PrayerCalculationMethod(val display: String) {
    UmmAlQura("Umm al-Qura (Saudi Arabia)"),
    MuslimWorldLeague("Muslim World League"),
    Egyptian("Egyptian General Authority"),
    Karachi("Karachi (University of Islamic Sciences)"),
    Dubai("Dubai"),
    Qatar("Qatar"),
    Kuwait("Kuwait"),
    MoonsightingCommittee("Moonsighting Committee"),
    Singapore("Singapore"),
    NorthAmerica("North America (ISNA)"),
    ;

    companion object {
        fun fromStorage(raw: String?): PrayerCalculationMethod =
            entries.firstOrNull { it.name == raw } ?: UmmAlQura
    }
}

enum class PrayerMadhab(val display: String) {
    Shafi("Shafi / Maliki / Hanbali"),
    Hanafi("Hanafi"),
    ;

    companion object {
        fun fromStorage(raw: String?): PrayerMadhab =
            entries.firstOrNull { it.name == raw } ?: Shafi
    }
}

data class PrayerSettingsSnapshot(
    val method: PrayerCalculationMethod = PrayerCalculationMethod.UmmAlQura,
    val madhab: PrayerMadhab = PrayerMadhab.Shafi,
    val notifyEachPrayer: Boolean = true,
    val playAthanAtFajr: Boolean = true,
)
