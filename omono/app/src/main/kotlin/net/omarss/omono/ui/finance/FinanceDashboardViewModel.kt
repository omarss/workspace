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
import net.omarss.omono.feature.spending.computeTotalsForMonth
import java.text.SimpleDateFormat
import java.time.Instant
import java.time.YearMonth
import java.time.ZoneId
import java.util.Locale
import javax.inject.Inject

@HiltViewModel
class FinanceDashboardViewModel @Inject constructor(
    private val repository: SpendingRepository,
    private val settings: SpendingSettingsRepository,
) : ViewModel() {

    private val zone = ZoneId.systemDefault()

    // Cached raw transactions so switching months doesn't need to
    // re-query the SMS inbox — a month toggle just re-aggregates the
    // in-memory list.
    private var transactionsCache: List<Transaction> = emptyList()
    private var selectedMonth: YearMonth = YearMonth.now(zone)

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
            transactionsCache = repository.recentTransactions()
            render()
        }
    }

    fun selectMonth(month: YearMonth) {
        if (month == selectedMonth) return
        selectedMonth = month
        viewModelScope.launch { render() }
    }

    private suspend fun render() {
        val budget = settings.monthlyBudgetSar.first()
        val categoryBudgets = settings.categoryBudgets.first()
        val current = YearMonth.now(zone)
        val isCurrent = selectedMonth == current
        val totals = if (isCurrent) {
            computeTotals(transactionsCache, Instant.now(), zone)
        } else {
            computeTotalsForMonth(transactionsCache, selectedMonth, zone)
        }
        val inSelectedMonth = transactionsCache.filterIn(selectedMonth, zone)
        val projectedMonthSar = if (isCurrent) projectMonthEnd(totals.monthSar) else 0.0

        _uiState.value = FinanceDashboardUiState(
            ready = true,
            selectedMonth = selectedMonth,
            availableMonths = buildAvailableMonths(current),
            isCurrentMonth = isCurrent,
            todaySar = totals.todaySar,
            monthSar = totals.monthSar,
            projectedMonthSar = projectedMonthSar,
            monthTransfersSar = totals.monthTransfersSar,
            monthRefundsSar = totals.monthRefundsSar,
            monthCount = totals.monthCount,
            lastMonthToDateSar = totals.lastMonthToDateSar,
            dailyAverageSar = totals.dailyAverageSar,
            budgetSar = budget,
            categoryBreakdown = buildCategoryRows(
                totals.monthByCategory, totals.monthSar, categoryBudgets,
            ),
            topMerchants = buildTopMerchants(inSelectedMonth),
            bills = buildBills(inSelectedMonth),
            transfers = buildTransfers(inSelectedMonth),
            recent = buildRecent(transactionsCache),
        )
    }

    fun setCategoryBudget(category: SpendingCategory, valueSar: Double) {
        viewModelScope.launch {
            settings.setCategoryBudget(category, valueSar)
            render()
        }
    }

    // Linear projection: extrapolate today's accumulated spend to the
    // end of the month assuming the same daily rate. Refuses to project
    // in the first two days because a single day's spending biases the
    // number into the absurd (one Jahez lunch × 30 is not a forecast).
    private fun projectMonthEnd(monthSar: Double): Double {
        val today = java.time.LocalDate.now(zone)
        val dayOfMonth = today.dayOfMonth
        val daysInMonth = today.lengthOfMonth()
        if (dayOfMonth < 2 || monthSar <= 0.0) return 0.0
        return monthSar * daysInMonth / dayOfMonth
    }

    // A fixed six-month rolling window ending at the current month. The
    // underlying SMS store only holds ~180 days of history, so anything
    // older just renders as empty totals rather than going missing.
    private fun buildAvailableMonths(current: YearMonth): List<YearMonth> =
        (0 until 6).map { current.minusMonths(it.toLong()) }

    private fun buildCategoryRows(
        byCategory: Map<SpendingCategory, Double>,
        monthSar: Double,
        categoryBudgets: Map<SpendingCategory, Double>,
    ): List<CategoryRow> {
        // Show every category that has spending OR a configured budget,
        // so a budgeted-but-unspent category still appears (with zero
        // spend) as a reminder that the budget exists.
        val categories = byCategory.keys + categoryBudgets.keys
        return categories.map { category ->
            val amount = byCategory[category] ?: 0.0
            val budget = categoryBudgets[category] ?: 0.0
            CategoryRow(
                category = category,
                amountSar = amount,
                budgetSar = budget,
                share = if (monthSar > 0) (amount / monthSar).toFloat() else 0f,
            )
        }.sortedByDescending { it.amountSar }
    }

    private fun buildTopMerchants(thisMonth: List<Transaction>): List<MerchantRow> {
        val purchases = thisMonth.filter { it.kind.isPurchaseForUi() }
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
                    id = "${tx.bank}-${tx.timestampMillis}-${tx.amountSar}",
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

private fun List<Transaction>.filterIn(ym: YearMonth, zone: ZoneId): List<Transaction> {
    val start = ym.atDay(1).atStartOfDay(zone).toInstant().toEpochMilli()
    val end = ym.plusMonths(1).atDay(1).atStartOfDay(zone).toInstant().toEpochMilli()
    return filter { it.timestampMillis in start until end }
}

// Transfers and refunds are not purchases for the "top merchants"
// screen — the same filter as `isPurchase` at the domain level but
// spelled out here so the UI logic doesn't accidentally widen if the
// domain rule ever changes.
private fun Transaction.Kind.isPurchaseForUi(): Boolean = when (this) {
    Transaction.Kind.TRANSFER_OUT,
    Transaction.Kind.REFUND -> false
    else -> true
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
    val selectedMonth: YearMonth = YearMonth.now(),
    val availableMonths: List<YearMonth> = emptyList(),
    val isCurrentMonth: Boolean = true,
    val todaySar: Double = 0.0,
    val monthSar: Double = 0.0,
    val projectedMonthSar: Double = 0.0,
    val monthTransfersSar: Double = 0.0,
    val monthRefundsSar: Double = 0.0,
    val monthCount: Int = 0,
    val lastMonthToDateSar: Double = 0.0,
    val dailyAverageSar: Double = 0.0,
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

    // Pace vs last month through the same day-of-month. `None` while we
    // don't have a comparable window of history, or when the user is
    // browsing a historic month where the benchmark doesn't apply.
    val monthTrend: SpendTrend
        get() = if (isCurrentMonth) {
            SpendTrend.compare(monthSar, lastMonthToDateSar)
        } else {
            SpendTrend.None
        }

    // Pace vs rolling 30-day daily average. Only meaningful for the
    // current month — "today's pace" in a historic month is meaningless.
    val dayTrend: SpendTrend
        get() = if (isCurrentMonth) {
            SpendTrend.compare(todaySar, dailyAverageSar)
        } else {
            SpendTrend.None
        }
}

enum class SpendTrend {
    Below, Above, None;

    companion object {
        fun compare(actual: Double, benchmark: Double): SpendTrend = when {
            benchmark <= 0.0 -> None
            actual > benchmark -> Above
            else -> Below
        }
    }
}

data class CategoryRow(
    val category: SpendingCategory,
    val amountSar: Double,
    val budgetSar: Double,
    val share: Float,
) {
    // Fraction 0..1 for the budget progress bar; 0 when no budget is
    // set. >1.0 (over-budget) is clamped before rendering.
    val budgetProgress: Float
        get() = if (budgetSar > 0.0) {
            (amountSar / budgetSar).toFloat().coerceIn(0f, 1f)
        } else 0f

    val overBudget: Boolean
        get() = budgetSar > 0.0 && amountSar > budgetSar

    val hasBudget: Boolean get() = budgetSar > 0.0
}

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
