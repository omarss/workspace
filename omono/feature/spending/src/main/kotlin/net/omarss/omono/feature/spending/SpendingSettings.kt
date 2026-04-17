package net.omarss.omono.feature.spending

import android.content.Context
import androidx.datastore.preferences.core.doublePreferencesKey
import androidx.datastore.preferences.core.edit
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
}
