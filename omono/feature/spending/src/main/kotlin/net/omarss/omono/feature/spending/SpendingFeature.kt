package net.omarss.omono.feature.spending

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.onStart
import net.omarss.omono.core.service.FeatureId
import net.omarss.omono.core.service.FeatureMetadata
import net.omarss.omono.core.service.FeatureState
import net.omarss.omono.core.service.OmonoFeature
import javax.inject.Inject
import javax.inject.Singleton

// Pure formatter for the notification summary line. Lives at file
// scope so tests can lock in the exact wording without spinning up
// the feature's Android dependencies.
//
// Renders a ▲ / ▼ glyph next to each headline when we have a benchmark
// to compare against (today vs. rolling daily average, month vs. last
// month through the same day-of-month). No glyph when the benchmark is
// zero — early-month or first-time users shouldn't see misleading
// signals from an empty history.
internal fun formatSpendingSummary(totals: SpendingTotals): String {
    val todayMark = trendGlyph(totals.todaySar, totals.dailyAverageSar)
    val monthMark = trendGlyph(totals.monthSar, totals.lastMonthToDateSar)
    return "Today SAR %,.0f%s · Month SAR %,.0f%s".format(
        totals.todaySar, todayMark,
        totals.monthSar, monthMark,
    )
}

private fun trendGlyph(actual: Double, benchmark: Double): String = when {
    benchmark <= 0.0 -> ""
    actual > benchmark -> " ▲"
    else -> " ▼"
}

@Singleton
class SpendingFeature @Inject constructor(
    private val repository: SpendingRepository,
) : OmonoFeature {

    override val id: FeatureId = FeatureId("spending")

    override val metadata: FeatureMetadata = FeatureMetadata(
        displayName = "Spending tracker",
        description = "Reads Al Rajhi and STC Bank SMSes to show how much you've spent today and this month.",
        defaultEnabled = true,
    )

    override fun start(scope: CoroutineScope): Flow<FeatureState> =
        repository.observeInboxChanges()
            .map { buildState() }
            .onStart {
                // Permission check happens here instead of at
                // observation time so the first emission is either a
                // useful total or a clear error — the UI never sees a
                // blank flash.
                if (!repository.hasReadSmsPermission()) {
                    emit(FeatureState.Error("SMS access needed"))
                } else {
                    emit(buildState())
                }
            }
            .catch { error ->
                emit(FeatureState.Error(error.message ?: error::class.simpleName.orEmpty()))
            }

    override fun stop() = Unit

    private suspend fun buildState(): FeatureState {
        if (!repository.hasReadSmsPermission()) {
            return FeatureState.Error("SMS access needed")
        }
        val totals = repository.currentTotals()
        return FeatureState.Active(
            summary = formatSpendingSummary(totals),
            metadata = mapOf(
                FeatureState.META_SPENT_TODAY_SAR to totals.todaySar,
                FeatureState.META_SPENT_MONTH_SAR to totals.monthSar,
                FeatureState.META_TRANSFERS_MONTH_SAR to totals.monthTransfersSar,
            ),
        )
    }
}
