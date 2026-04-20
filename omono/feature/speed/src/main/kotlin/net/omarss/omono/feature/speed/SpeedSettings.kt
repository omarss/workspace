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
private val ALERT_ON_PHONE_USE_WHILE_DRIVING_KEY =
    booleanPreferencesKey("speed.alert_on_phone_use_while_driving")
private val DISABLE_INTERNET_WHILE_DRIVING_KEY =
    booleanPreferencesKey("speed.disable_internet_while_driving")
private val VOICE_ALERTS_ENABLED_KEY = booleanPreferencesKey("speed.voice_alerts_enabled")
private val VOICE_ALERT_LANGUAGE_KEY = stringPreferencesKey("speed.voice_alert_language")
private val VIBRATE_ONLY_KEY = booleanPreferencesKey("speed.vibrate_only")
private val FUN_MODE_KEY = booleanPreferencesKey("speed.fun_mode")

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

    // Replaces the beep / loop-beep with a spoken phrase in English or
    // Arabic. On by default — clearer to a distracted driver than a
    // tone, and if TTS isn't installed the player falls back to the
    // existing beep path automatically.
    val voiceAlertsEnabled: Flow<Boolean> = context.omonoDataStore.data.map { prefs ->
        prefs[VOICE_ALERTS_ENABLED_KEY] ?: true
    }

    // Auto = follow device locale (Arabic if the phone is set to any
    // Arabic variant, else English). Explicit picks override that.
    val voiceAlertLanguage: Flow<VoiceAlertLanguage> = context.omonoDataStore.data.map { prefs ->
        VoiceAlertLanguage.fromStorage(prefs[VOICE_ALERT_LANGUAGE_KEY])
    }

    // Replaces every audible alert (beep + TTS) with a vibration
    // pattern. For use in quiet places (meetings, mosques, late
    // night) where the user still wants the feedback. Off by
    // default — audible alerts are safer for driving.
    val vibrateOnly: Flow<Boolean> = context.omonoDataStore.data.map { prefs ->
        prefs[VIBRATE_ONLY_KEY] ?: false
    }

    // "Fun mode" — instead of the canned "Slow down, please" voice
    // line, speed alerts say a random phrase from a bundled list
    // (English or Arabic, per voiceAlertLanguage). Purely cosmetic,
    // off by default so a new install gets the straightforward
    // warning.
    val funMode: Flow<Boolean> = context.omonoDataStore.data.map { prefs ->
        prefs[FUN_MODE_KEY] ?: false
    }

    suspend fun setUnit(unit: SpeedUnit) {
        context.omonoDataStore.edit { it[UNIT_KEY] = unit.name }
    }

    suspend fun setAlertOnOverLimit(enabled: Boolean) {
        context.omonoDataStore.edit { it[ALERT_ON_OVER_LIMIT_KEY] = enabled }
    }

    suspend fun setAlertOnPhoneUseWhileDriving(enabled: Boolean) {
        context.omonoDataStore.edit { it[ALERT_ON_PHONE_USE_WHILE_DRIVING_KEY] = enabled }
    }

    suspend fun setDisableInternetWhileDriving(enabled: Boolean) {
        context.omonoDataStore.edit { it[DISABLE_INTERNET_WHILE_DRIVING_KEY] = enabled }
    }

    suspend fun setVoiceAlertsEnabled(enabled: Boolean) {
        context.omonoDataStore.edit { it[VOICE_ALERTS_ENABLED_KEY] = enabled }
    }

    suspend fun setVoiceAlertLanguage(language: VoiceAlertLanguage) {
        context.omonoDataStore.edit { it[VOICE_ALERT_LANGUAGE_KEY] = language.name }
    }

    suspend fun setVibrateOnly(enabled: Boolean) {
        context.omonoDataStore.edit { it[VIBRATE_ONLY_KEY] = enabled }
    }

    suspend fun setFunMode(enabled: Boolean) {
        context.omonoDataStore.edit { it[FUN_MODE_KEY] = enabled }
    }
}
