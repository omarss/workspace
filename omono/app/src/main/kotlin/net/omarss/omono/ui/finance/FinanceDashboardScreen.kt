package net.omarss.omono.ui.finance

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import net.omarss.omono.feature.spending.SpendingCategory
import net.omarss.omono.feature.spending.Transaction
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FinanceDashboardRoute(
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    viewModel: FinanceDashboardViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var editingBudget by remember { mutableStateOf<SpendingCategory?>(null) }

    editingBudget?.let { category ->
        val existing = state.categoryBreakdown
            .firstOrNull { it.category == category }
            ?.budgetSar ?: 0.0
        CategoryBudgetDialog(
            category = category,
            currentSar = existing,
            onSave = { amount ->
                viewModel.setCategoryBudget(category, amount)
                editingBudget = null
            },
            onDismiss = { editingBudget = null },
        )
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
    ) {
        TopAppBar(
            title = { Text("Finance") },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                }
            },
        )

        if (state.error != null) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(32.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    text = state.error.orEmpty(),
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
            return@Column
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            MonthChipRow(
                months = state.availableMonths,
                selected = state.selectedMonth,
                onSelect = viewModel::selectMonth,
            )
            SummaryCard(state)
            BudgetCard(state)
            if (state.categoryBreakdown.isNotEmpty()) {
                CategoryBreakdownCard(
                    rows = state.categoryBreakdown,
                    onEditBudget = { editingBudget = it },
                )
            }
            if (state.topMerchants.isNotEmpty()) {
                TopMerchantsCard(state.topMerchants)
            }
            if (state.bills.isNotEmpty()) {
                BillsCard(state.bills)
            }
            if (state.transfers.isNotEmpty()) {
                TransfersCard(state.monthTransfersSar, state.transfers)
            }
            if (state.recent.isNotEmpty()) {
                RecentTransactionsCard(state.recent)
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

// Horizontal chip row listing the last N months, newest on the left.
// Tapping a month re-aggregates totals against that window. Current
// month shows an extra marker so the user can eyeball which row drives
// today/daily-average/pace-vs-last-month — pace pills disappear when a
// non-current month is selected.
@Composable
private fun MonthChipRow(
    months: List<YearMonth>,
    selected: YearMonth,
    onSelect: (YearMonth) -> Unit,
) {
    if (months.isEmpty()) return
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        val current = YearMonth.now()
        months.forEach { ym ->
            val label = when (ym) {
                current -> "This month"
                current.minusMonths(1) -> "Last month"
                else -> ym.format(MONTH_CHIP_FMT)
            }
            FilterChip(
                selected = ym == selected,
                onClick = { onSelect(ym) },
                label = { Text(label) },
                colors = FilterChipDefaults.filterChipColors(),
            )
        }
    }
}

private val MONTH_CHIP_FMT: DateTimeFormatter =
    DateTimeFormatter.ofPattern("MMM yyyy", Locale.getDefault())

// Per-category budget editor. An empty amount clears the budget so
// the row falls back to share-only display.
@Composable
private fun CategoryBudgetDialog(
    category: SpendingCategory,
    currentSar: Double,
    onSave: (Double) -> Unit,
    onDismiss: () -> Unit,
) {
    var text by remember {
        mutableStateOf(if (currentSar > 0.0) "%.0f".format(currentSar) else "")
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Budget for ${category.label}") },
        text = {
            Column {
                Text(
                    "Monthly limit in SAR for this category. " +
                        "Leave empty to remove the budget.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = text,
                    onValueChange = { new ->
                        text = new.filter { it.isDigit() || it == '.' }
                    },
                    label = { Text("SAR") },
                    singleLine = true,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(text.toDoubleOrNull() ?: 0.0) }) {
                Text("Save")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        },
    )
}

@Composable
private fun SummaryCard(state: FinanceDashboardUiState) {
    val gradientColors = listOf(
        MaterialTheme.colorScheme.primary,
        MaterialTheme.colorScheme.tertiary
    )
    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        shape = MaterialTheme.shapes.large,
        colors = CardDefaults.cardColors(containerColor = Color.Transparent),
        elevation = CardDefaults.elevatedCardElevation(defaultElevation = 8.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(Brush.linearGradient(gradientColors))
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = if (state.isCurrentMonth) "This month" else state.selectedMonth.format(MONTH_CHIP_FMT),
                style = MaterialTheme.typography.labelLarge,
                color = Color.White.copy(alpha = 0.8f),
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "SAR %,.0f".format(state.monthSar),
                    style = MaterialTheme.typography.displaySmall,
                    color = Color.White,
                )
                TrendPill(
                    trend = state.monthTrend,
                    actual = state.monthSar,
                    benchmark = state.lastMonthToDateSar,
                    modifier = Modifier.padding(start = 12.dp),
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                val subtitle = if (state.isCurrentMonth) {
                    "${state.monthCount} purchases · Today SAR %,.0f".format(state.todaySar)
                } else {
                    "${state.monthCount} purchases"
                }
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color.White.copy(alpha = 0.8f),
                )
                if (state.isCurrentMonth) {
                    TrendPill(
                        trend = state.dayTrend,
                        actual = state.todaySar,
                        benchmark = state.dailyAverageSar,
                        modifier = Modifier.padding(start = 8.dp),
                    )
                }
            }
            if (state.projectedMonthSar > 0.0) {
                Text(
                    text = "On pace for SAR %,.0f by month-end".format(state.projectedMonthSar),
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.White.copy(alpha = 0.85f),
                )
            }
            if (state.monthRefundsSar > 0.0) {
                Text(
                    text = "+ SAR %,.0f refunded".format(state.monthRefundsSar),
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(0xFFA7F3D0), // emerald 200 — reads on indigo→violet gradient
                )
            }
        }
    }
}

// Small arrow + delta chip indicating whether the headline number is
// pacing below or above its benchmark. Rendered inline next to the
// total it qualifies. Hidden when the benchmark is zero (no history).
@Composable
private fun TrendPill(
    trend: SpendTrend,
    actual: Double,
    benchmark: Double,
    modifier: Modifier = Modifier,
) {
    if (trend == SpendTrend.None || benchmark <= 0.0) return
    val bg = when (trend) {
        SpendTrend.Below -> Color(0xFF10B981) // emerald 500
        SpendTrend.Above -> Color(0xFFDC2626) // red 600
        SpendTrend.None -> Color.Transparent
    }
    val arrow = if (trend == SpendTrend.Below) "▼" else "▲"
    val deltaPct = ((actual - benchmark) / benchmark * 100.0)
    Box(
        modifier = modifier
            .background(bg, RoundedCornerShape(50))
            .padding(horizontal = 10.dp, vertical = 4.dp),
    ) {
        Text(
            text = "%s %+.0f%%".format(arrow, deltaPct),
            style = MaterialTheme.typography.labelMedium,
            color = Color.White,
        )
    }
}

@Composable
private fun BudgetCard(state: FinanceDashboardUiState) {
    if (state.budgetSar <= 0) return
    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = "Monthly budget",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            val progressColor = if (state.overBudget) {
                MaterialTheme.colorScheme.error
            } else {
                MaterialTheme.colorScheme.primary
            }
            LinearProgressIndicator(
                progress = { state.budgetProgress },
                modifier = Modifier.fillMaxWidth(),
                color = progressColor,
                trackColor = MaterialTheme.colorScheme.surfaceVariant,
            )
            Text(
                text = "SAR %,.0f / SAR %,.0f · %.0f%%".format(
                    state.monthSar,
                    state.budgetSar,
                    state.budgetProgress * 100,
                ),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun CategoryBreakdownCard(
    rows: List<CategoryRow>,
    onEditBudget: (SpendingCategory) -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = "By category · tap to set budget",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            rows.forEach { row ->
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onEditBudget(row.category) }
                        .padding(vertical = 2.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = row.category.label,
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.weight(1f),
                        )
                        val amountColor = when {
                            row.overBudget -> MaterialTheme.colorScheme.error
                            else -> MaterialTheme.colorScheme.onSurface
                        }
                        val amountText = if (row.hasBudget) {
                            "SAR %,.0f / %,.0f".format(row.amountSar, row.budgetSar)
                        } else {
                            "SAR %,.0f".format(row.amountSar)
                        }
                        Text(
                            text = amountText,
                            style = MaterialTheme.typography.bodyMedium,
                            color = amountColor,
                        )
                    }
                    // Share-of-month bar stays the same — this is the
                    // "how big a slice of the month is this category"
                    // signal. Budget tracking gets its own bar below.
                    LinearProgressIndicator(
                        progress = { row.share },
                        modifier = Modifier.fillMaxWidth(),
                        color = MaterialTheme.colorScheme.primary,
                        trackColor = MaterialTheme.colorScheme.surfaceVariant,
                    )
                    if (row.hasBudget) {
                        LinearProgressIndicator(
                            progress = { row.budgetProgress },
                            modifier = Modifier.fillMaxWidth(),
                            color = if (row.overBudget) {
                                MaterialTheme.colorScheme.error
                            } else {
                                Color(0xFF10B981) // emerald — distinct from the share bar
                            },
                            trackColor = MaterialTheme.colorScheme.surfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun TopMerchantsCard(rows: List<MerchantRow>) {
    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = "Top merchants",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            rows.forEachIndexed { index, row ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = row.merchant,
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            text = row.category.label,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Text(
                        text = "SAR %,.0f".format(row.amountSar),
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }
    }
}

@Composable
private fun BillsCard(rows: List<BillRow>) {
    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = "Bills & government",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            rows.forEachIndexed { index, row ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = row.label,
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        val subtitle = if (row.count > 1) {
                            "${row.count} payments · ${kindLabel(row.kind)}"
                        } else {
                            kindLabel(row.kind)
                        }
                        Text(
                            text = subtitle,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Text(
                        text = "SAR %,.0f".format(row.amountSar),
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }
    }
}

@Composable
private fun TransfersCard(totalSar: Double, rows: List<TransferRow>) {
    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = "Transfers this month",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSecondaryContainer,
            )
            Text(
                text = "SAR %,.0f".format(totalSar),
                style = MaterialTheme.typography.headlineSmall,
                color = MaterialTheme.colorScheme.onSecondaryContainer,
            )
            Text(
                text = "Outgoing transfers aren't counted toward the monthly purchase total.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSecondaryContainer,
            )
            rows.forEachIndexed { index, row ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.2f))
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = row.recipient,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSecondaryContainer,
                        )
                        Text(
                            text = row.date,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSecondaryContainer,
                        )
                    }
                    Text(
                        text = formatAmount(row.amountSar, row.originalAmount, row.originalCurrency),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSecondaryContainer,
                    )
                }
            }
        }
    }
}

// "SAR 863 (USD 230)" for foreign currency, "SAR 72" for SAR.
private fun formatAmount(amountSar: Double, originalAmount: Double, originalCurrency: String): String =
    if (originalCurrency == "SAR") {
        "SAR %,.0f".format(amountSar)
    } else {
        "SAR %,.0f · %s %,.2f".format(amountSar, originalCurrency, originalAmount)
    }

@Composable
private fun RecentTransactionsCard(rows: List<RecentRow>) {
    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = "Recent activity",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            rows.forEachIndexed { index, row ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                }
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(
                        text = row.date,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = row.merchant,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                            Text(
                                text = kindLabel(row.kind) + " · " + bankLabel(row.bank),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        val amountColor = when (row.kind) {
                            Transaction.Kind.TRANSFER_OUT -> MaterialTheme.colorScheme.secondary
                            Transaction.Kind.REFUND -> Color(0xFF10B981) // emerald — money back in
                            else -> MaterialTheme.colorScheme.onSurface
                        }
                        val amountText = formatAmount(row.amountSar, row.originalAmount, row.originalCurrency)
                        Text(
                            text = if (row.kind == Transaction.Kind.REFUND) "+$amountText" else amountText,
                            style = MaterialTheme.typography.bodyMedium,
                            color = amountColor,
                        )
                    }
                }
            }
        }
    }
}

private fun kindLabel(kind: Transaction.Kind): String = when (kind) {
    Transaction.Kind.POS -> "Point of sale"
    Transaction.Kind.ONLINE_PURCHASE -> "Online purchase"
    Transaction.Kind.BILLER -> "Bill payment"
    Transaction.Kind.CASH_WITHDRAWAL -> "Cash withdrawal"
    Transaction.Kind.GOVT_PAYMENT -> "Government payment"
    Transaction.Kind.TRANSFER_OUT -> "Transfer out"
    Transaction.Kind.REFUND -> "Refund"
}

private fun bankLabel(bank: Transaction.Bank): String = when (bank) {
    Transaction.Bank.AL_RAJHI -> "Al Rajhi"
    Transaction.Bank.STC -> "STC Bank"
}
