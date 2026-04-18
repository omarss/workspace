package net.omarss.omono.feature.speed

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.core.data.omonoDataStore
import javax.inject.Inject
import javax.inject.Singleton

// Per-feature key prefix keeps speed prefs cleanly isolated inside the
// shared omonoDataStore. New features should use their own prefix
// (e.g. "noise.threshold") rather than spawning a sibling DataStore.
private val UNIT_KEY = stringPreferencesKey("speed.unit")
private val ALERT_ON_OVER_LIMIT_KEY = booleanPreferencesKey("speed.alert_on_over_limit")
private val ALERT_ON_TRAFFIC_AHEAD_KEY = booleanPreferencesKey("speed.alert_on_traffic_ahead")
private val ALERT_ON_PHONE_USE_WHILE_DRIVING_KEY =
    booleanPreferencesKey("speed.alert_on_phone_use_while_driving")
private val DISABLE_INTERNET_WHILE_DRIVING_KEY =
    booleanPreferencesKey("speed.disable_internet_while_driving")

@Singleton
class SpeedSettingsRepository @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {
    val unit: Flow<SpeedUnit> = context.omonoDataStore.data.map { prefs ->
        prefs[UNIT_KEY]?.let { saved -> runCatching { SpeedUnit.valueOf(saved) }.getOrNull() }
            ?: SpeedUnit.KmH
    }

    // Loud beep when the user crosses the posted speed limit. On by
    // default so the feature is discoverable from first launch.
    val alertOnOverLimit: Flow<Boolean> = context.omonoDataStore.data.map { prefs ->
        prefs[ALERT_ON_OVER_LIMIT_KEY] ?: true
    }

    // Heads-up tone when the road ~500m ahead is significantly slower
    // than free-flow. Off by default — costs TomTom quota and can be
    // noisy on heavily-congested city drives.
    val alertOnTrafficAhead: Flow<Boolean> = context.omonoDataStore.data.map { prefs ->
        prefs[ALERT_ON_TRAFFIC_AHEAD_KEY] ?: false
    }

    // Loops a loud beep whenever the screen turns on while the app
    // thinks the user is driving. Off by default — opt-in because it
    // intentionally makes the phone unpleasant to pick up mid-drive.
    val alertOnPhoneUseWhileDriving: Flow<Boolean> = context.omonoDataStore.data.map { prefs ->
        prefs[ALERT_ON_PHONE_USE_WHILE_DRIVING_KEY] ?: false
    }

    // Turns Wi-Fi + mobile data off when the user starts driving, back
    // on when the trip ends. Requires Shizuku (grants ADB-level
    // perms without root). Off by default. The setting being on with
    // Shizuku not ready is a no-op — the governor silently refuses.
    val disableInternetWhileDriving: Flow<Boolean> = context.omonoDataStore.data.map { prefs ->
        prefs[DISABLE_INTERNET_WHILE_DRIVING_KEY] ?: false
    }

    suspend fun setUnit(unit: SpeedUnit) {
        context.omonoDataStore.edit { it[UNIT_KEY] = unit.name }
    }

    suspend fun setAlertOnOverLimit(enabled: Boolean) {
        context.omonoDataStore.edit { it[ALERT_ON_OVER_LIMIT_KEY] = enabled }
    }

    suspend fun setAlertOnTrafficAhead(enabled: Boolean) {
        context.omonoDataStore.edit { it[ALERT_ON_TRAFFIC_AHEAD_KEY] = enabled }
    }

    suspend fun setAlertOnPhoneUseWhileDriving(enabled: Boolean) {
        context.omonoDataStore.edit { it[ALERT_ON_PHONE_USE_WHILE_DRIVING_KEY] = enabled }
    }

    suspend fun setDisableInternetWhileDriving(enabled: Boolean) {
        context.omonoDataStore.edit { it[DISABLE_INTERNET_WHILE_DRIVING_KEY] = enabled }
    }
}
