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
private val ATHAN_SELECTION_KEY = stringPreferencesKey("prayer.athan_selection")
private val RELIABILITY_KEY = booleanPreferencesKey("prayer.reliability_mode")
private val CHALLENGE_KEY = booleanPreferencesKey("prayer.require_challenge")

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

    // Random = rotate; Specific = pin one filename. Default Random.
    val athanSelection: Flow<AthanSelection> = context.omonoDataStore.data.map { prefs ->
        AthanSelection.fromStorage(prefs[ATHAN_SELECTION_KEY])
    }

    // "Reliability mode" — when on, omono runs a low-priority
    // foreground service that keeps the app process alive across
    // overnight idle periods so AlarmManager can fire reliably even
    // on aggressive OEMs (Samsung / Xiaomi / Huawei) that kill
    // background processes. Off by default — most users on stock
    // Android don't need it, and the persistent notification it
    // posts costs UX visibility.
    val reliabilityMode: Flow<Boolean> = context.omonoDataStore.data.map { prefs ->
        prefs[RELIABILITY_KEY] ?: false
    }

    // Anti-snooze gate: when on, the Fajr athan cannot be dismissed
    // until the user answers FAJR_CHALLENGE_REQUIRED questions
    // correctly in a row. Off by default — opt in via the Prayer
    // tab. Off for users who just want a normal alarm; on for users
    // who sleep through everything short of an exam.
    val requireChallengeToStop: Flow<Boolean> = context.omonoDataStore.data.map { prefs ->
        prefs[CHALLENGE_KEY] ?: false
    }

    // Convenience combine for downstream code that needs all fields
    // in one snapshot. combine's public overloads top out at 5
    // flows, so we split into two halves and merge.
    private val coreSnapshot: Flow<CoreSnapshot> = combine(
        method, madhab, notifyEachPrayer, playAthanAtFajr, athanSelection,
    ) { m, mh, notify, athan, selection ->
        CoreSnapshot(m, mh, notify, athan, selection)
    }

    private val modesSnapshot: Flow<ModesSnapshot> = combine(
        reliabilityMode, requireChallengeToStop,
    ) { rel, challenge -> ModesSnapshot(rel, challenge) }

    val snapshot: Flow<PrayerSettingsSnapshot> = combine(
        coreSnapshot, modesSnapshot,
    ) { core, modes ->
        PrayerSettingsSnapshot(
            method = core.method,
            madhab = core.madhab,
            notifyEachPrayer = core.notifyEachPrayer,
            playAthanAtFajr = core.playAthanAtFajr,
            athanSelection = core.athanSelection,
            reliabilityMode = modes.reliabilityMode,
            requireChallengeToStop = modes.requireChallenge,
        )
    }

    private data class CoreSnapshot(
        val method: PrayerCalculationMethod,
        val madhab: PrayerMadhab,
        val notifyEachPrayer: Boolean,
        val playAthanAtFajr: Boolean,
        val athanSelection: AthanSelection,
    )

    private data class ModesSnapshot(
        val reliabilityMode: Boolean,
        val requireChallenge: Boolean,
    )

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

    suspend fun setAthanSelection(selection: AthanSelection) {
        context.omonoDataStore.edit {
            it[ATHAN_SELECTION_KEY] = AthanSelection.toStorage(selection)
        }
    }

    suspend fun setReliabilityMode(enabled: Boolean) {
        context.omonoDataStore.edit { it[RELIABILITY_KEY] = enabled }
    }

    suspend fun setRequireChallengeToStop(enabled: Boolean) {
        context.omonoDataStore.edit { it[CHALLENGE_KEY] = enabled }
    }
}
