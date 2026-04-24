package net.omarss.omono.feature.prayer

import android.content.Context
import androidx.datastore.preferences.core.doublePreferencesKey
import androidx.datastore.preferences.core.edit
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import net.omarss.omono.core.data.omonoDataStore
import javax.inject.Inject
import javax.inject.Singleton

// Remembers the last GPS fix we used to compute prayer times so the
// app can render *something* on cold start before the GPS settles —
// and more importantly, so a user with the GPS disabled (or standing
// in a basement) still sees accurate-ish times for their usual
// location. The ViewModel checks the cache on init and uses it as
// the seed until a fresher fix overwrites it.
//
// Only the latitude + longitude are persisted — accuracy, speed,
// bearing etc. don't help the calculator and aren't worth the bytes.

@Singleton
class PrayerLocationCache @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {
    data class Fix(val latitude: Double, val longitude: Double)

    val last: Flow<Fix?> = context.omonoDataStore.data.map { prefs ->
        val lat = prefs[LAT_KEY]
        val lon = prefs[LON_KEY]
        if (lat != null && lon != null) Fix(lat, lon) else null
    }

    suspend fun save(latitude: Double, longitude: Double) {
        context.omonoDataStore.edit { prefs ->
            prefs[LAT_KEY] = latitude
            prefs[LON_KEY] = longitude
        }
    }

    private companion object {
        val LAT_KEY = doublePreferencesKey("prayer.last_lat")
        val LON_KEY = doublePreferencesKey("prayer.last_lon")
    }
}
