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

    suspend fun setUnit(unit: SpeedUnit) {
        context.omonoDataStore.edit { it[UNIT_KEY] = unit.name }
    }

    suspend fun setAlertOnOverLimit(enabled: Boolean) {
        context.omonoDataStore.edit { it[ALERT_ON_OVER_LIMIT_KEY] = enabled }
    }
}
