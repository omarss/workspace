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
sealed interface FeatureState {
    val summary: String

    data class Active(override val summary: String) : FeatureState

    data class Idle(override val summary: String = "Idle") : FeatureState

    data class Error(val message: String) : FeatureState {
        override val summary: String get() = "Error: $message"
    }
}
