package net.omarss.omono.ui.finance

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import net.omarss.omono.feature.spending.MerchantCategorizer
import net.omarss.omono.feature.spending.SpendingCategory
import net.omarss.omono.feature.spending.SpendingRepository
import net.omarss.omono.feature.spending.SpendingSettingsRepository
import net.omarss.omono.feature.spending.Transaction
import net.omarss.omono.feature.spending.computeTotals
import java.text.SimpleDateFormat
import java.time.Instant
import java.time.ZoneId
import java.util.Locale
import javax.inject.Inject

@HiltViewModel
class FinanceDashboardViewModel @Inject constructor(
    private val repository: SpendingRepository,
    private val settings: SpendingSettingsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(FinanceDashboardUiState())
    val uiState: StateFlow<FinanceDashboardUiState> = _uiState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            if (!repository.hasReadSmsPermission()) {
                _uiState.value = FinanceDashboardUiState(error = "SMS access needed")
                return@launch
            }
            val transactions = repository.recentTransactions()
            val totals = computeTotals(
                transactions = transactions,
                now = Instant.now(),
                zone = ZoneId.systemDefault(),
            )
            val budget = settings.monthlyBudgetSar.first()

            _uiState.value = FinanceDashboardUiState(
                ready = true,
                todaySar = totals.todaySar,
                monthSar = totals.monthSar,
                monthTransfersSar = totals.monthTransfersSar,
                monthCount = totals.monthCount,
                budgetSar = budget,
                categoryBreakdown = buildCategoryRows(totals.monthByCategory, totals.monthSar),
                topMerchants = buildTopMerchants(transactions),
                recent = buildRecent(transactions),
            )
        }
    }

    private fun buildCategoryRows(
        byCategory: Map<SpendingCategory, Double>,
        monthSar: Double,
    ): List<CategoryRow> = byCategory.entries
        .sortedByDescending { it.value }
        .map { (category, amount) ->
            CategoryRow(
                category = category,
                amountSar = amount,
                share = if (monthSar > 0) (amount / monthSar).toFloat() else 0f,
            )
        }

    private fun buildTopMerchants(transactions: List<Transaction>): List<MerchantRow> {
        val startOfMonth = Instant.now().atZone(ZoneId.systemDefault())
            .toLocalDate().withDayOfMonth(1)
            .atStartOfDay(ZoneId.systemDefault())
            .toInstant().toEpochMilli()
        val thisMonth = transactions.filter {
            it.timestampMillis >= startOfMonth && it.kind != Transaction.Kind.TRANSFER_OUT
        }
        val bucketed = thisMonth
            .groupBy { (it.merchant ?: "Unknown").trim() }
            .mapValues { (_, list) -> list.sumOf { it.amountSar } }
        return bucketed.entries
            .sortedByDescending { it.value }
            .take(5)
            .map { (merchant, amount) ->
                MerchantRow(
                    merchant = merchant,
                    amountSar = amount,
                    category = MerchantCategorizer.categorize(merchant),
                )
            }
    }

    private fun buildRecent(transactions: List<Transaction>): List<RecentRow> {
        val fmt = SimpleDateFormat("EEE d MMM · HH:mm", Locale.getDefault())
        return transactions
            .sortedByDescending { it.timestampMillis }
            .take(20)
            .map { tx ->
                RecentRow(
                    id = "${tx.bank}-${tx.timestampMillis}-${tx.amountSar}",
                    date = fmt.format(tx.timestampMillis),
                    merchant = tx.merchant ?: "(no merchant)",
                    amountSar = tx.amountSar,
                    kind = tx.kind,
                    bank = tx.bank,
                )
            }
    }
}

data class FinanceDashboardUiState(
    val ready: Boolean = false,
    val todaySar: Double = 0.0,
    val monthSar: Double = 0.0,
    val monthTransfersSar: Double = 0.0,
    val monthCount: Int = 0,
    val budgetSar: Double = 0.0,
    val categoryBreakdown: List<CategoryRow> = emptyList(),
    val topMerchants: List<MerchantRow> = emptyList(),
    val recent: List<RecentRow> = emptyList(),
    val error: String? = null,
) {
    val budgetProgress: Float
        get() = if (budgetSar > 0) (monthSar / budgetSar).toFloat().coerceIn(0f, 1f) else 0f

    val overBudget: Boolean
        get() = budgetSar > 0 && monthSar > budgetSar
}

data class CategoryRow(
    val category: SpendingCategory,
    val amountSar: Double,
    val share: Float,
)

data class MerchantRow(
    val merchant: String,
    val amountSar: Double,
    val category: SpendingCategory,
)

data class RecentRow(
    val id: String,
    val date: String,
    val merchant: String,
    val amountSar: Double,
    val kind: Transaction.Kind,
    val bank: Transaction.Bank,
)
