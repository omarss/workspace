package net.omarss.omono.feature.speed

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.onStart
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.core.service.FeatureId
import net.omarss.omono.core.service.FeatureMetadata
import net.omarss.omono.core.service.FeatureState
import net.omarss.omono.core.service.OmonoFeature
import javax.inject.Inject
import javax.inject.Singleton

// Speeds reported by FusedLocation below this threshold are unreliable
// (GPS noise dominates). We render them as "—" so the notification
// doesn't flicker when the user is standing still.
private const val STATIONARY_THRESHOLD_MPS = 0.5f

@Singleton
class SpeedFeature @Inject constructor(
    private val speedRepository: SpeedRepository,
    private val settings: SpeedSettingsRepository,
) : OmonoFeature {

    override val id: FeatureId = FeatureId("speed")

    override val metadata: FeatureMetadata = FeatureMetadata(
        displayName = "Speed monitor",
        description = "Shows your current GPS speed in an always-on notification.",
        defaultEnabled = true,
    )

    override fun start(scope: CoroutineScope): Flow<FeatureState> =
        combine(
            speedRepository.speedMetersPerSecond(),
            settings.unit,
        ) { mps, unit -> render(mps, unit) }
            .onStart { emit(FeatureState.Idle("Waiting for GPS fix")) }
            .catch { error ->
                emit(FeatureState.Error(error.message ?: error::class.simpleName.orEmpty()))
            }

    override fun stop() = Unit

    private fun render(mps: Float, unit: SpeedUnit): FeatureState {
        if (mps < STATIONARY_THRESHOLD_MPS) {
            return FeatureState.Idle("— ${unit.label}")
        }
        val converted = unit.fromMetersPerSecond(mps)
        return FeatureState.Active("%.1f %s".format(converted, unit.label))
    }
}
