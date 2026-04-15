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
            val thisMonth = transactions.filterInThisMonth()

            _uiState.value = FinanceDashboardUiState(
                ready = true,
                todaySar = totals.todaySar,
                monthSar = totals.monthSar,
                monthTransfersSar = totals.monthTransfersSar,
                monthCount = totals.monthCount,
                budgetSar = budget,
                categoryBreakdown = buildCategoryRows(totals.monthByCategory, totals.monthSar),
                topMerchants = buildTopMerchants(thisMonth),
                bills = buildBills(thisMonth),
                transfers = buildTransfers(thisMonth),
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

    private fun buildTopMerchants(thisMonth: List<Transaction>): List<MerchantRow> {
        val purchases = thisMonth.filter { it.kind != Transaction.Kind.TRANSFER_OUT }
        val bucketed = purchases
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

    // Bills = biller payments + government payments (Saher/MOI).
    // Grouped by label so repeat electricity bills collapse into one
    // row with the total amount and a count.
    private fun buildBills(thisMonth: List<Transaction>): List<BillRow> {
        val billKinds = setOf(Transaction.Kind.BILLER, Transaction.Kind.GOVT_PAYMENT)
        val bills = thisMonth.filter { it.kind in billKinds }
        return bills
            .groupBy { billLabel(it) }
            .map { (label, list) ->
                BillRow(
                    label = label,
                    amountSar = list.sumOf { it.amountSar },
                    count = list.size,
                    kind = list.first().kind,
                )
            }
            .sortedByDescending { it.amountSar }
    }

    private fun buildTransfers(thisMonth: List<Transaction>): List<TransferRow> {
        val fmt = SimpleDateFormat("d MMM", Locale.getDefault())
        return thisMonth
            .filter { it.kind == Transaction.Kind.TRANSFER_OUT }
            .sortedByDescending { it.timestampMillis }
            .map { tx ->
                TransferRow(
                    id = "${tx.bank}-${tx.timestampMillis}",
                    recipient = tx.merchant ?: "Unknown recipient",
                    date = fmt.format(tx.timestampMillis),
                    amountSar = tx.amountSar,
                    originalAmount = tx.originalAmount,
                    originalCurrency = tx.originalCurrency,
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
                    originalAmount = tx.originalAmount,
                    originalCurrency = tx.originalCurrency,
                    kind = tx.kind,
                    bank = tx.bank,
                )
            }
    }
}

private fun List<Transaction>.filterInThisMonth(): List<Transaction> {
    val startOfMonth = Instant.now().atZone(ZoneId.systemDefault())
        .toLocalDate().withDayOfMonth(1)
        .atStartOfDay(ZoneId.systemDefault())
        .toInstant().toEpochMilli()
    return filter { it.timestampMillis >= startOfMonth }
}

// Human-friendly name for a bill row. Prefers the merchant/service
// field when present; otherwise falls back to the transaction kind.
// Special-cases traffic violations (Saher) since they come through as
// GOVT_PAYMENT with merchant "Traffic Violations Payment".
private fun billLabel(tx: Transaction): String {
    val merchant = tx.merchant?.trim().orEmpty()
    if (merchant.isNotEmpty()) {
        val lower = merchant.lowercase()
        return when {
            "traffic" in lower -> "Saher (traffic violations)"
            "saudi electricity" in lower || "sec" == lower -> "Electricity"
            "stc" in lower -> "STC"
            "mobily" in lower -> "Mobily"
            "zain" in lower -> "Zain"
            "water" in lower || "nwc" in lower -> "Water"
            "ejar" in lower -> "Ejar (rent)"
            "internet" in lower -> "Internet"
            else -> merchant
        }
    }
    return when (tx.kind) {
        Transaction.Kind.GOVT_PAYMENT -> "Government payment"
        Transaction.Kind.BILLER -> "Bill payment"
        else -> "Payment"
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
    val bills: List<BillRow> = emptyList(),
    val transfers: List<TransferRow> = emptyList(),
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

data class BillRow(
    val label: String,
    val amountSar: Double,
    val count: Int,
    val kind: Transaction.Kind,
)

data class TransferRow(
    val id: String,
    val recipient: String,
    val date: String,
    val amountSar: Double,
    val originalAmount: Double,
    val originalCurrency: String,
)

data class RecentRow(
    val id: String,
    val date: String,
    val merchant: String,
    val amountSar: Double,
    val originalAmount: Double,
    val originalCurrency: String,
    val kind: Transaction.Kind,
    val bank: Transaction.Bank,
) {
    val isForeignCurrency: Boolean
        get() = originalCurrency != "SAR"
}
