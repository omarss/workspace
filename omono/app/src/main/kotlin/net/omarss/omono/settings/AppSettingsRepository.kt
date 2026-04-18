package net.omarss.omono.settings

import android.content.Context
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

    suspend fun setTheme(preference: ThemePreference) {
        context.omonoDataStore.edit { it[THEME_KEY] = preference.name }
    }

    private companion object {
        val THEME_KEY = stringPreferencesKey("app.theme")
    }
}
