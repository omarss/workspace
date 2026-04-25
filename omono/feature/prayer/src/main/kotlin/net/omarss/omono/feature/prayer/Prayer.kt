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

// How the Fajr athan is picked from whatever files the user has
// dropped into the athans directory. `Random` is the default — it
// rotates through whatever's present. `Specific(fileName)` pins a
// single filename; if that file is missing on disk (e.g. the user
// deleted it) the player falls back to Random.
sealed interface AthanSelection {
    data object Random : AthanSelection
    data class Specific(val fileName: String) : AthanSelection

    companion object {
        fun fromStorage(raw: String?): AthanSelection = when {
            raw.isNullOrBlank() || raw == RANDOM_TOKEN -> Random
            raw.startsWith(SPECIFIC_PREFIX) -> Specific(raw.removePrefix(SPECIFIC_PREFIX))
            else -> Random
        }

        fun toStorage(selection: AthanSelection): String = when (selection) {
            Random -> RANDOM_TOKEN
            is Specific -> SPECIFIC_PREFIX + selection.fileName
        }

        private const val RANDOM_TOKEN = "random"
        private const val SPECIFIC_PREFIX = "file:"
    }
}

data class PrayerSettingsSnapshot(
    val method: PrayerCalculationMethod = PrayerCalculationMethod.UmmAlQura,
    val madhab: PrayerMadhab = PrayerMadhab.Shafi,
    val notifyEachPrayer: Boolean = true,
    val playAthanAtFajr: Boolean = true,
    val athanSelection: AthanSelection = AthanSelection.Random,
    val reliabilityMode: Boolean = false,
)

// Pure guard for whether the athan should play on a given alarm
// firing. Extracted so the test suite can lock the Fajr-only rule
// without instantiating the BroadcastReceiver. Rule:
//   * Athan plays only at Fajr.
//   * Athan plays only if the user hasn't disabled it.
// Any drift from those two constraints is a regression.
fun shouldPlayAthan(kind: PrayerKind, settings: PrayerSettingsSnapshot): Boolean =
    kind == PrayerKind.Fajr && settings.playAthanAtFajr
