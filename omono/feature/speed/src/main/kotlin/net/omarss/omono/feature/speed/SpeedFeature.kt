package net.omarss.omono.feature.speed

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flow
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
internal const val STATIONARY_THRESHOLD_MPS: Float = 0.5f

// Pure formatter — exposed at file scope so it's trivial to unit-test
// without instantiating SpeedFeature or its Android dependencies.
internal fun formatSpeedState(
    mps: Float,
    unit: SpeedUnit,
    limitKmh: Float? = null,
): FeatureState {
    val convertedSpeed = unit.fromMetersPerSecond(mps)
    val speedKmh = SpeedUnit.KmH.fromMetersPerSecond(mps)
    val metadata = buildMap<String, Double> {
        put(FeatureState.META_SPEED_KMH, speedKmh.toDouble())
        if (limitKmh != null) put(FeatureState.META_SPEED_LIMIT_KMH, limitKmh.toDouble())
    }

    if (mps < STATIONARY_THRESHOLD_MPS) {
        return FeatureState.Idle(
            summary = "— ${unit.label}",
            metadata = metadata,
        )
    }

    // Convert the OSM-stored km/h limit into the user's chosen unit so
    // both numbers in the notification share the same scale.
    val limitSuffix = limitKmh?.let { kmh ->
        val limitMps = kmh / 3.6f
        " (limit %.0f %s)".format(unit.fromMetersPerSecond(limitMps), unit.label)
    } ?: ""
    return FeatureState.Active(
        summary = "%.1f %s%s".format(convertedSpeed, unit.label, limitSuffix),
        metadata = metadata,
    )
}

@Singleton
class SpeedFeature @Inject constructor(
    private val speedRepository: SpeedRepository,
    private val limits: RoadSpeedLimitRepository,
    private val settings: SpeedSettingsRepository,
) : OmonoFeature {

    override val id: FeatureId = FeatureId("speed")

    override val metadata: FeatureMetadata = FeatureMetadata(
        displayName = "Speed monitor",
        description = "Shows your current GPS speed and the road's posted limit in an always-on notification.",
        defaultEnabled = true,
    )

    override fun start(scope: CoroutineScope): Flow<FeatureState> {
        // Each new GPS sample triggers a (cached, distance-throttled)
        // speed-limit lookup. The repository handles deduping internally
        // so this is cheap on a moving vehicle and free when stationary.
        val locationsWithLimit = flow {
            speedRepository.locations().collect { snapshot ->
                val limit = limits.limitKmh(snapshot.latitude, snapshot.longitude)
                emit(snapshot.speedMps to limit)
            }
        }

        return combine(locationsWithLimit, settings.unit) { (mps, limit), unit ->
            formatSpeedState(mps, unit, limit)
        }
            .onStart { emit(FeatureState.Idle("Waiting for GPS fix")) }
            .catch { error ->
                emit(FeatureState.Error(error.message ?: error::class.simpleName.orEmpty()))
            }
    }

    override fun stop() = Unit
}
