package net.omarss.omono.feature.speed

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import net.omarss.omono.core.service.FeatureId
import net.omarss.omono.core.service.FeatureMetadata
import net.omarss.omono.core.service.FeatureState
import net.omarss.omono.core.service.OmonoFeature
import javax.inject.Inject
import javax.inject.Singleton

// Scaffold implementation of the speed feature. Real GPS wiring
// (FusedLocationProviderClient → Flow<Speed>) lands in the next step.
@Singleton
class SpeedFeature @Inject constructor() : OmonoFeature {

    override val id: FeatureId = FeatureId("speed")

    override val metadata: FeatureMetadata = FeatureMetadata(
        displayName = "Speed monitor",
        description = "Shows your current GPS speed in an always-on notification.",
        defaultEnabled = true,
    )

    override fun start(scope: CoroutineScope): Flow<FeatureState> =
        flowOf(FeatureState.Idle(summary = "Waiting for GPS fix"))

    override fun stop() = Unit
}
