package net.omarss.omono.feature.places

import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

// Great-circle distance in metres. Accurate within ±0.5% up to a
// few thousand km — comfortably enough for POI ranging (< 50 km).
internal fun haversineMeters(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val r = 6_371_000.0
    val dLat = Math.toRadians(lat2 - lat1)
    val dLon = Math.toRadians(lon2 - lon1)
    val a = sin(dLat / 2).let { it * it } +
        cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) *
        sin(dLon / 2).let { it * it }
    val c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return r * c
}

// Initial bearing from (lat1, lon1) toward (lat2, lon2) in degrees,
// normalised to [0, 360). 0° = north, 90° = east, etc. Used by the
// direction-cone filter and the compass-arrow UI.
internal fun bearingDegrees(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Float {
    val phi1 = Math.toRadians(lat1)
    val phi2 = Math.toRadians(lat2)
    val deltaLambda = Math.toRadians(lon2 - lon1)
    val y = sin(deltaLambda) * cos(phi2)
    val x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(deltaLambda)
    val theta = atan2(y, x)
    return ((Math.toDegrees(theta) + 360) % 360).toFloat()
}
