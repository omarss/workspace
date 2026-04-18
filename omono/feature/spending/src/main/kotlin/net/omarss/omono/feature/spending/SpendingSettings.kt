package net.omarss.omono.feature.spending

import android.content.Context
import androidx.datastore.preferences.core.doublePreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import net.omarss.omono.core.data.omonoDataStore
import javax.inject.Inject
import javax.inject.Singleton

// DataStore-backed preferences for the spending feature. Uses the
// "spending.*" key prefix to stay cleanly isolated from the speed
// feature's prefs inside the shared omonoDataStore.
private val MONTHLY_BUDGET_SAR_KEY = doublePreferencesKey("spending.monthly_budget_sar")

// Default monthly budget until the user sets their own. Arbitrary but
// generous for a single-household use case in SA.
private const val DEFAULT_MONTHLY_BUDGET_SAR: Double = 3000.0

// Per-category budget keys are generated from the enum name so adding
// a new SpendingCategory doesn't require a DataStore migration — the
// key just starts returning null until the user sets a value.
private fun categoryBudgetKey(category: SpendingCategory) =
    doublePreferencesKey("spending.budget.category.${category.name}")

// Category overrides (user tap-to-correct on a transaction). Stored
// as a single serialised string — "{normalisedMerchant}|{category};…" —
// because preferences-DataStore has no native Map support and a
// single string keeps the read path to one lookup per transaction.
private val CATEGORY_OVERRIDES_KEY = stringPreferencesKey("spending.category_overrides")
private const val OVERRIDE_ENTRY_SEP = ";"
private const val OVERRIDE_KV_SEP = "|"

@Singleton
class SpendingSettingsRepository @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {
    val monthlyBudgetSar: Flow<Double> = context.omonoDataStore.data.map { prefs ->
        prefs[MONTHLY_BUDGET_SAR_KEY] ?: DEFAULT_MONTHLY_BUDGET_SAR
    }

    // Emits only categories that have a positive configured budget.
    // A missing key and a zero-value key both mean "no budget set" —
    // keeps the UI layer simple (absence vs zero is the same signal).
    val categoryBudgets: Flow<Map<SpendingCategory, Double>> =
        context.omonoDataStore.data.map { prefs ->
            SpendingCategory.entries.mapNotNull { category ->
                val value = prefs[categoryBudgetKey(category)] ?: 0.0
                if (value > 0.0) category to value else null
            }.toMap()
        }

    // Map from normalised merchant key (lowercased + trimmed raw SMS
    // field) → user-chosen SpendingCategory. Consulted *before* the
    // keyword-based MerchantCategorizer so "correcting" one row fixes
    // every past and future transaction with the same merchant.
    val categoryOverrides: Flow<Map<String, SpendingCategory>> =
        context.omonoDataStore.data.map { prefs ->
            parseOverrides(prefs[CATEGORY_OVERRIDES_KEY].orEmpty())
        }

    suspend fun setMonthlyBudgetSar(value: Double) {
        val clamped = value.coerceAtLeast(0.0)
        context.omonoDataStore.edit { it[MONTHLY_BUDGET_SAR_KEY] = clamped }
    }

    // value ≤ 0 clears the budget for this category.
    suspend fun setCategoryBudget(category: SpendingCategory, value: Double) {
        context.omonoDataStore.edit { prefs ->
            val key = categoryBudgetKey(category)
            if (value > 0.0) {
                prefs[key] = value
            } else {
                prefs.remove(key)
            }
        }
    }

    // Adds or overwrites the category the user has pinned for a
    // given merchant. Normalisation (lowercase + trim + collapse
    // whitespace) matches the lookup key used by MerchantCategorizer.
    suspend fun setCategoryOverride(merchantRaw: String, category: SpendingCategory) {
        val key = normaliseMerchantKey(merchantRaw)
        if (key.isEmpty()) return
        context.omonoDataStore.edit { prefs ->
            val map = parseOverrides(prefs[CATEGORY_OVERRIDES_KEY].orEmpty()).toMutableMap()
            map[key] = category
            prefs[CATEGORY_OVERRIDES_KEY] = serialiseOverrides(map)
        }
    }

    suspend fun clearCategoryOverride(merchantRaw: String) {
        val key = normaliseMerchantKey(merchantRaw)
        if (key.isEmpty()) return
        context.omonoDataStore.edit { prefs ->
            val map = parseOverrides(prefs[CATEGORY_OVERRIDES_KEY].orEmpty()).toMutableMap()
            map.remove(key)
            if (map.isEmpty()) {
                prefs.remove(CATEGORY_OVERRIDES_KEY)
            } else {
                prefs[CATEGORY_OVERRIDES_KEY] = serialiseOverrides(map)
            }
        }
    }
}

// Same normalisation used by MerchantCategorizer so that lookups
// hit even when SMS casing varies.
internal fun normaliseMerchantKey(raw: String): String =
    raw.trim().lowercase().replace(Regex("\\s+"), " ")

private fun parseOverrides(serialised: String): Map<String, SpendingCategory> {
    if (serialised.isBlank()) return emptyMap()
    val out = mutableMapOf<String, SpendingCategory>()
    for (entry in serialised.split(OVERRIDE_ENTRY_SEP)) {
        if (entry.isBlank()) continue
        val idx = entry.indexOf(OVERRIDE_KV_SEP)
        if (idx <= 0) continue
        val key = entry.substring(0, idx)
        val value = entry.substring(idx + 1)
        val category = SpendingCategory.entries.firstOrNull { it.name == value } ?: continue
        out[key] = category
    }
    return out
}

private fun serialiseOverrides(map: Map<String, SpendingCategory>): String =
    map.entries.joinToString(OVERRIDE_ENTRY_SEP) { (k, v) -> "$k$OVERRIDE_KV_SEP${v.name}" }
