package net.omarss.omono.ui.compass

import android.hardware.GeomagneticField
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin

// Geographic coordinates of the Kaaba. These are the canonical values
// used by prayer-time apps (Islamic Finder, Muslim Pro, Google's
// own qibla compass). Stable enough to hard-code.
private const val KAABA_LAT_DEG = 21.4224779
private const val KAABA_LON_DEG = 39.8251832

// Initial great-circle bearing from (userLat, userLon) to the Kaaba,
// in degrees clockwise from TRUE north. Returns a value in [0, 360).
// Pure function — no Android dependency, trivially unit-testable.
//
// Derivation (standard great-circle navigation):
//   y = sin(Δλ) · cos(φ₂)
//   x = cos(φ₁) · sin(φ₂) − sin(φ₁) · cos(φ₂) · cos(Δλ)
//   θ = atan2(y, x)
//
// Because the user's phone compass reads MAGNETIC north (see
// HeadingSensor), a naive subtraction of heading from this bearing
// is off by the local magnetic declination. Use `trueToMagnetic()`
// below (or the equivalent declination-correction in CompassViewModel)
// to reconcile the two reference frames before driving the UI.
fun qiblaBearingDeg(userLat: Double, userLon: Double): Double {
    val phi1 = Math.toRadians(userLat)
    val phi2 = Math.toRadians(KAABA_LAT_DEG)
    val dLambda = Math.toRadians(KAABA_LON_DEG - userLon)
    val y = sin(dLambda) * cos(phi2)
    val x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(dLambda)
    val theta = Math.toDegrees(atan2(y, x))
    return (theta + 360.0) % 360.0
}

// Local magnetic declination (degrees east-positive) at the given
// position and moment in time. Wraps Android's `GeomagneticField`
// — the WMM model ships in-platform so this doesn't need a network
// round-trip. Altitude is passed as 0 m because it only changes the
// answer by a hundredth of a degree at civil altitudes; not worth
// the sensor plumbing.
fun magneticDeclinationDeg(
    latitude: Double,
    longitude: Double,
    timestampMillis: Long = System.currentTimeMillis(),
): Float = GeomagneticField(
    latitude.toFloat(),
    longitude.toFloat(),
    0f,
    timestampMillis,
).declination

// True bearing → magnetic bearing at (lat, lon). Subtract the
// declination because an east-positive declination means magnetic
// north is east of true north, so the same direction has a smaller
// magnetic reading.
fun trueToMagneticDeg(trueBearing: Float, lat: Double, lon: Double): Float {
    val declination = magneticDeclinationDeg(lat, lon)
    return ((trueBearing - declination) % 360f + 360f) % 360f
}

// Magnetic bearing → true bearing. Equivalent: `mag + declination`.
// Used to lift the HeadingSensor's magnetic-referenced azimuth into
// the true frame that all of omono's place bearings live in.
fun magneticToTrueDeg(magneticBearing: Float, lat: Double, lon: Double): Float {
    val declination = magneticDeclinationDeg(lat, lon)
    return ((magneticBearing + declination) % 360f + 360f) % 360f
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
