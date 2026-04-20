package net.omarss.omono.feature.places

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringSetPreferencesKey
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import net.omarss.omono.core.data.omonoDataStore
import javax.inject.Inject
import javax.inject.Singleton

// Places-tab preferences. Currently only one dimension — which
// categories the user has chosen to hide from the chip row — but the
// repository stays open for future additions (custom category
// ordering, default search radius override, etc.) without a second
// DataStore instance.
//
// Storage is the shared `omonoDataStore` under the `places.*` prefix
// so every pref keeps to its feature's namespace.
private val HIDDEN_CATEGORIES_KEY = stringSetPreferencesKey("places.hidden_categories")

@Singleton
class PlacesSettingsRepository @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {
    // The set of PlaceCategory names the user has chosen to hide. An
    // empty set means "show everything" (the default on fresh install)
    // so a new user never sees a blanked-out Places tab.
    val hiddenCategories: Flow<Set<PlaceCategory>> = context.omonoDataStore.data.map { prefs ->
        val raw = prefs[HIDDEN_CATEGORIES_KEY] ?: emptySet()
        raw.mapNotNullTo(HashSet()) { name ->
            runCatching { PlaceCategory.valueOf(name) }.getOrNull()
        }
    }

    suspend fun setHiddenCategories(hidden: Set<PlaceCategory>) {
        context.omonoDataStore.edit { prefs ->
            prefs[HIDDEN_CATEGORIES_KEY] = hidden.mapTo(HashSet()) { it.name }
        }
    }

    suspend fun toggleHidden(category: PlaceCategory, hidden: Boolean) {
        context.omonoDataStore.edit { prefs ->
            val current = prefs[HIDDEN_CATEGORIES_KEY]?.toMutableSet() ?: mutableSetOf()
            if (hidden) current += category.name else current -= category.name
            prefs[HIDDEN_CATEGORIES_KEY] = current
        }
    }
}
