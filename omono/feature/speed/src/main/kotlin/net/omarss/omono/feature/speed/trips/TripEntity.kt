package net.omarss.omono.feature.speed.trips

import androidx.room.Entity
import androidx.room.PrimaryKey

// One completed trip persisted to Room. Distance is computed via
// haversine over the location samples; max/avg speed are derived from
// the same stream. We intentionally don't persist the full path for
// MVP — it's a forever-growing blob and the list view doesn't need
// it. Future versions can add a separate path table if a map screen
// needs it.
@Entity(tableName = "trips")
data class TripEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val startAtMillis: Long,
    val endAtMillis: Long,
    val distanceMeters: Double,
    val maxSpeedKmh: Float,
    val avgSpeedKmh: Float,
)
