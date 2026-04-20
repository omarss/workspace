package net.omarss.omono.feature.places

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.core.stringSetPreferencesKey
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import net.omarss.omono.core.data.omonoDataStore
import javax.inject.Inject
import javax.inject.Singleton

// Places-tab preferences. Two dimensions so far — which categories
// the user has chosen to hide from the chip row, and a custom order
// they can shuffle categories into. Any category not present in the
// ordering falls back to the enum's natural order, so a fresh
// install with no preference set renders the original curated order
// without a migration step.
//
// Storage is the shared `omonoDataStore` under the `places.*` prefix
// so every pref keeps to its feature's namespace.
private val HIDDEN_CATEGORIES_KEY = stringSetPreferencesKey("places.hidden_categories")
private val CATEGORY_ORDER_KEY = stringPreferencesKey("places.category_order")

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

    // User-preferred ordering for the chip row. Returns the full list
    // of categories — any slug absent from the stored preference is
    // appended in enum order at the end, so a fresh install renders
    // the curated default until the user touches the customize sheet.
    val orderedCategories: Flow<List<PlaceCategory>> =
        context.omonoDataStore.data.map { prefs ->
            val raw = prefs[CATEGORY_ORDER_KEY]
            applyOrder(raw)
        }

    suspend fun setOrder(order: List<PlaceCategory>) {
        context.omonoDataStore.edit { prefs ->
            prefs[CATEGORY_ORDER_KEY] = order.joinToString(",") { it.name }
        }
    }

    // Clears every Places preference back to defaults — hidden set
    // empty, order back to enum order. Used by the "Reset" action on
    // the customize sheet.
    suspend fun reset() {
        context.omonoDataStore.edit { prefs ->
            prefs.remove(HIDDEN_CATEGORIES_KEY)
            prefs.remove(CATEGORY_ORDER_KEY)
        }
    }

    // Move a category up or down in the stored order by one slot.
    // No-op at the edges so the UI can call blindly without guarding
    // on position.
    suspend fun move(category: PlaceCategory, up: Boolean) {
        context.omonoDataStore.edit { prefs ->
            val current = applyOrder(prefs[CATEGORY_ORDER_KEY]).toMutableList()
            val index = current.indexOf(category)
            if (index < 0) return@edit
            val target = if (up) index - 1 else index + 1
            if (target !in current.indices) return@edit
            current[index] = current[target]
            current[target] = category
            prefs[CATEGORY_ORDER_KEY] = current.joinToString(",") { it.name }
        }
    }

    // Drag-and-drop reorder primitive. Takes the source category
    // out of its current slot and re-inserts it at the target
    // category's slot, shifting every category between by one —
    // same semantics as a classic drag-reorder gesture.
    suspend fun reorder(from: PlaceCategory, to: PlaceCategory) {
        if (from == to) return
        context.omonoDataStore.edit { prefs ->
            val current = applyOrder(prefs[CATEGORY_ORDER_KEY]).toMutableList()
            val fromIdx = current.indexOf(from)
            val toIdx = current.indexOf(to)
            if (fromIdx < 0 || toIdx < 0 || fromIdx == toIdx) return@edit
            current.removeAt(fromIdx)
            current.add(toIdx, from)
            prefs[CATEGORY_ORDER_KEY] = current.joinToString(",") { it.name }
        }
    }

    // Merges a stored order string with the enum so every category
    // has a deterministic position even when the preference is empty
    // or lists a subset. Unknown slugs (from a stale rename or a
    // forward-compat edit) are silently dropped.
    private fun applyOrder(raw: String?): List<PlaceCategory> {
        if (raw.isNullOrBlank()) return PlaceCategory.entries
        val ordered = raw.split(",").mapNotNull { name ->
            runCatching { PlaceCategory.valueOf(name.trim()) }.getOrNull()
        }
        val seen = ordered.toHashSet()
        val tail = PlaceCategory.entries.filter { it !in seen }
        return ordered + tail
    }
}
