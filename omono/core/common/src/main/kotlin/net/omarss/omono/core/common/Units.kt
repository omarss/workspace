package net.omarss.omono.core.common

// Speed unit domain model shared across modules.
// Conversions from raw m/s (Location#getSpeed) live here so every feature
// formats consistently.
enum class SpeedUnit(val label: String) {
    KmH("km/h"),
    Mph("mph"),
    Ms("m/s"),
    ;

    fun fromMetersPerSecond(ms: Float): Float = when (this) {
        KmH -> ms * 3.6f
        Mph -> ms * 2.2369363f
        Ms -> ms
    }
}
