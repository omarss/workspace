package net.omarss.omono.feature.speed.trips

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface TripDao {

    // Most-recent first, limited to 20 so the list screen never loads
    // more than a sensible window. Infinite scroll can be added later.
    @Query("SELECT * FROM trips ORDER BY startAtMillis DESC LIMIT 20")
    fun observeRecent(): Flow<List<TripEntity>>

    @Query("SELECT * FROM trips ORDER BY startAtMillis DESC LIMIT 5")
    fun observeTop5(): Flow<List<TripEntity>>

    @Insert
    suspend fun insert(trip: TripEntity): Long

    @Query("DELETE FROM trips")
    suspend fun clear()

    @Query("SELECT COUNT(*) FROM trips")
    suspend fun count(): Int
}
