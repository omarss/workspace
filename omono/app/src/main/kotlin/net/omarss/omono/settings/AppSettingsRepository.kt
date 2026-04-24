package net.omarss.omono.settings

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import net.omarss.omono.core.data.omonoDataStore
import javax.inject.Inject
import javax.inject.Singleton

// App-wide appearance preferences. Kept separate from SpeedSettings so
// the key namespace makes sense (`app.theme` not `speed.theme`) and
// other features can add their own app-level toggles here without
// growing the speed module's surface area.
enum class ThemePreference {
    // Follow the system dark / light mode setting.
    Auto,
    Light,
    Dark,
    ;

    companion object {
        fun fromStorage(raw: String?): ThemePreference =
            entries.firstOrNull { it.name == raw } ?: Auto
    }
}

@Singleton
class AppSettingsRepository @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    val theme: Flow<ThemePreference> = context.omonoDataStore.data.map { prefs ->
        ThemePreference.fromStorage(prefs[THEME_KEY])
    }

    // "When a doc finishes reading, automatically open the next doc in
    // the same subject and continue." On by default — the whole point
    // of the docs tab is hands-free reading on a drive.
    val docsAutoAdvance: Flow<Boolean> = context.omonoDataStore.data.map { prefs ->
        prefs[DOCS_AUTO_ADVANCE_KEY] ?: true
    }

    // Persisted voice name for the docs reader. null = auto-pick (the
    // DocsTtsPlayer picks the highest-quality offline voice for the
    // device locale). Set to a specific TextToSpeech.Voice.name to
    // pin that voice — values are opaque engine-scoped strings like
    // "en-us-x-sfg#female_1-local".
    val docsTtsVoiceName: Flow<String?> = context.omonoDataStore.data.map { prefs ->
        prefs[DOCS_TTS_VOICE_KEY]
    }

    suspend fun setTheme(preference: ThemePreference) {
        context.omonoDataStore.edit { it[THEME_KEY] = preference.name }
    }

    suspend fun setDocsAutoAdvance(enabled: Boolean) {
        context.omonoDataStore.edit { it[DOCS_AUTO_ADVANCE_KEY] = enabled }
    }

    suspend fun setDocsTtsVoiceName(name: String?) {
        context.omonoDataStore.edit { prefs ->
            if (name == null) prefs.remove(DOCS_TTS_VOICE_KEY) else prefs[DOCS_TTS_VOICE_KEY] = name
        }
    }

    private companion object {
        val THEME_KEY = stringPreferencesKey("app.theme")
        val DOCS_AUTO_ADVANCE_KEY = booleanPreferencesKey("app.docs_auto_advance")
        val DOCS_TTS_VOICE_KEY = stringPreferencesKey("app.docs_tts_voice")
    }
}
