package net.omarss.omono.ui.compass

import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin

// Geographic coordinates of the Kaaba. These are the canonical values
// used by prayer-time apps (Islamic Finder, Muslim Pro, Google's
// own qibla compass). Stable enough to hard-code.
private const val KAABA_LAT_DEG = 21.4224779
private const val KAABA_LON_DEG = 39.8251832

// Initial great-circle bearing from (userLat, userLon) to the Kaaba,
// in degrees clockwise from true north. Returns a value in [0, 360).
// Pure function — no Android dependency, trivially unit-testable.
fun qiblaBearingDeg(userLat: Double, userLon: Double): Double {
    val phi1 = Math.toRadians(userLat)
    val phi2 = Math.toRadians(KAABA_LAT_DEG)
    val dLambda = Math.toRadians(KAABA_LON_DEG - userLon)
    val y = sin(dLambda) * cos(phi2)
    val x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(dLambda)
    val theta = Math.toDegrees(atan2(y, x))
    return (theta + 360.0) % 360.0
}

// Maps a compass bearing to the 8-wind cardinal / intercardinal
// abbreviation used throughout the UI. 0° = N, 90° = E, etc., with
// each wind claiming a 45° sector centred on its true bearing.
fun compassLabel(bearingDeg: Float): String {
    val normalised = ((bearingDeg % 360f) + 360f) % 360f
    return when {
        normalised < 22.5f || normalised >= 337.5f -> "N"
        normalised < 67.5f -> "NE"
        normalised < 112.5f -> "E"
        normalised < 157.5f -> "SE"
        normalised < 202.5f -> "S"
        normalised < 247.5f -> "SW"
        normalised < 292.5f -> "W"
        else -> "NW"
    }
}
