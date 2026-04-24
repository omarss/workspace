package net.omarss.omono.feature.prayer

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import net.omarss.omono.core.data.omonoDataStore
import javax.inject.Inject
import javax.inject.Singleton

// Per-feature prefix prayer.* sits alongside speed.*, app.* inside the
// shared omonoDataStore.
private val METHOD_KEY = stringPreferencesKey("prayer.method")
private val MADHAB_KEY = stringPreferencesKey("prayer.madhab")
private val NOTIFY_KEY = booleanPreferencesKey("prayer.notify_each")
private val ATHAN_KEY = booleanPreferencesKey("prayer.athan_at_fajr")

@Singleton
class PrayerSettingsRepository @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {
    val method: Flow<PrayerCalculationMethod> = context.omonoDataStore.data.map { prefs ->
        PrayerCalculationMethod.fromStorage(prefs[METHOD_KEY])
    }

    val madhab: Flow<PrayerMadhab> = context.omonoDataStore.data.map { prefs ->
        PrayerMadhab.fromStorage(prefs[MADHAB_KEY])
    }

    val notifyEachPrayer: Flow<Boolean> = context.omonoDataStore.data.map { prefs ->
        prefs[NOTIFY_KEY] ?: true
    }

    val playAthanAtFajr: Flow<Boolean> = context.omonoDataStore.data.map { prefs ->
        prefs[ATHAN_KEY] ?: true
    }

    // Convenience combine for downstream code that needs all four in
    // one snapshot — the repository uses this to avoid holding four
    // independent coroutines.
    val snapshot: Flow<PrayerSettingsSnapshot> = combine(
        method, madhab, notifyEachPrayer, playAthanAtFajr,
    ) { m, mh, notify, athan ->
        PrayerSettingsSnapshot(
            method = m,
            madhab = mh,
            notifyEachPrayer = notify,
            playAthanAtFajr = athan,
        )
    }

    suspend fun setMethod(method: PrayerCalculationMethod) {
        context.omonoDataStore.edit { it[METHOD_KEY] = method.name }
    }

    suspend fun setMadhab(madhab: PrayerMadhab) {
        context.omonoDataStore.edit { it[MADHAB_KEY] = madhab.name }
    }

    suspend fun setNotifyEachPrayer(enabled: Boolean) {
        context.omonoDataStore.edit { it[NOTIFY_KEY] = enabled }
    }

    suspend fun setPlayAthanAtFajr(enabled: Boolean) {
        context.omonoDataStore.edit { it[ATHAN_KEY] = enabled }
    }
}
