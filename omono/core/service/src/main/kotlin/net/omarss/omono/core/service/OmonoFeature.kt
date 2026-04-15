package net.omarss.omono.core.service

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow

// The extensibility contract.
//
// A feature is a self-contained unit of background work — speed tracker,
// step counter, noise monitor, whatever. The host service discovers all
// OmonoFeature bindings via Hilt multibinding (@IntoSet), starts the ones
// the user has enabled, and aggregates their state flows into notifications.
//
// Adding a new feature is therefore: new Gradle module + @Binds @IntoSet.
// Zero changes to :app or :core.
interface OmonoFeature {

    val id: FeatureId

    val metadata: FeatureMetadata

    // Start the feature and return a hot flow of its current state. The
    // host service collects this flow for the feature's lifetime.
    //
    // The provided scope is cancelled when the feature is stopped.
    fun start(scope: CoroutineScope): Flow<FeatureState>

    fun stop()
}

@JvmInline
value class FeatureId(val value: String)

data class FeatureMetadata(
    val displayName: String,
    val description: String,
    val defaultEnabled: Boolean,
)

// Features emit their current tracked value plus a human-readable summary
// the notification can render directly. Keeping summary in the state avoids
// the host needing to know anything about each feature's semantics.
//
// `metadata` is an opt-in escape hatch for richer UI: features can stash
// typed values (the speed feature uses it for current m/s, current km/h,
// and the local speed limit) and the UI layer pulls them out by key.
// Notifications still render only `summary`, so this never leaks into
// the host service.
sealed interface FeatureState {
    val summary: String

    data class Active(
        override val summary: String,
        val metadata: Map<String, Double> = emptyMap(),
    ) : FeatureState

    data class Idle(
        override val summary: String = "Idle",
        val metadata: Map<String, Double> = emptyMap(),
    ) : FeatureState

    data class Error(val message: String) : FeatureState {
        override val summary: String get() = "Error: $message"
    }

    companion object {
        // Well-known metadata keys. Features are free to use their own;
        // these are documented here so the UI layer doesn't
        // string-literal them everywhere.
        const val META_SPEED_KMH: String = "speed.kmh"
        const val META_SPEED_LIMIT_KMH: String = "speed.limit_kmh"
        const val META_SPENT_TODAY_SAR: String = "spending.today_sar"
        const val META_SPENT_MONTH_SAR: String = "spending.month_sar"
        const val META_TRANSFERS_MONTH_SAR: String = "spending.transfers_month_sar"
    }
}
