package net.omarss.omono.feature.speed

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.onStart
import kotlinx.coroutines.launch
import timber.log.Timber
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.core.service.FeatureId
import net.omarss.omono.core.service.FeatureMetadata
import net.omarss.omono.core.service.FeatureState
import net.omarss.omono.core.service.OmonoFeature
import net.omarss.omono.feature.speed.trips.TripRecorder
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
    private val alertPlayer: SpeedAlertPlayer,
    private val tripRecorder: TripRecorder,
    private val trafficWatcher: TrafficAheadWatcher,
    private val drivingDetector: DrivingModeDetector,
    private val distractionGuard: DistractionGuard,
    private val driveInternetGate: DriveInternetGate,
) : OmonoFeature {

    override val id: FeatureId = FeatureId("speed")

    override val metadata: FeatureMetadata = FeatureMetadata(
        displayName = "Speed monitor",
        description = "Shows your current GPS speed and the road's posted limit in an always-on notification.",
        defaultEnabled = true,
    )

    // Carries the previous over-limit state between emissions so we can
    // fire the alert tone only on a rising edge, not on every sample
    // while already over the limit.
    private var wasOverLimit: Boolean = false

    override fun start(scope: CoroutineScope): Flow<FeatureState> {
        // Each new GPS sample triggers a (cached, distance-throttled)
        // speed-limit lookup and feeds the trip recorder so trip history
        // captures the same location stream as the notification.
        val locationsWithLimit = flow {
            speedRepository.locations().collect { snapshot ->
                tripRecorder.onLocation(snapshot)
                drivingDetector.onSample(snapshot.speedMps, System.currentTimeMillis())
                // Fire-and-forget so a slow TomTom round-trip never
                // blocks the speedometer UI. The watcher owns its own
                // throttle + dedupe state.
                scope.launch {
                    if (!settings.alertOnTrafficAhead.first()) return@launch
                    runCatching { trafficWatcher.onLocation(snapshot) }
                        .onFailure { Timber.w(it, "traffic watcher failed") }
                        .getOrNull()
                        ?.let { alertPlayer.alertTrafficAhead() }
                }
                val limit = limits.limitKmh(
                    lat = snapshot.latitude,
                    lon = snapshot.longitude,
                    bearingDeg = snapshot.bearingDeg,
                    bearingAccuracyDeg = snapshot.bearingAccuracyDeg,
                    speedMps = snapshot.speedMps,
                )
                emit(snapshot.speedMps to limit)
            }
        }

        // Reset transition memory each time the feature (re)starts so a
        // stop/start cycle doesn't suppress the first alert.
        wasOverLimit = false
        drivingDetector.reset()
        // Distraction guard runs alongside the main location stream —
        // it owns its own combine of driving × screen × setting and
        // drives the looping beep when all three line up.
        distractionGuard.attach(scope)
        // Internet governor works the same shape: observe driving ×
        // setting and shell out through Shizuku to disable / re-enable
        // Wi-Fi + mobile data at the drive boundaries.
        driveInternetGate.attach(scope)

        return combine(locationsWithLimit, settings.unit) { (mps, limit), unit ->
            maybeAlert(mps, limit)
            formatSpeedState(mps, unit, limit)
        }
            .onStart { emit(FeatureState.Idle("Waiting for GPS fix")) }
            .catch { error ->
                emit(FeatureState.Error(error.message ?: error::class.simpleName.orEmpty()))
            }
    }

    override fun stop() {
        tripRecorder.finalizeCurrent()
        drivingDetector.reset()
        alertPlayer.stopBeeping()
        // Fire-and-forget — OmonoFeature.stop() is non-suspending and
        // we must not leave the user offline if they tapped Stop
        // mid-drive. Uses a private IO scope (rather than GlobalScope)
        // so lint doesn't complain and so cancellation is contained.
        cleanupScope.launch {
            runCatching { driveInternetGate.ensureEnabledOnStop() }
                .onFailure { Timber.w(it, "drive internet gate cleanup failed") }
        }
    }

    // Dedicated scope for the stop() cleanup. SupervisorJob so a failed
    // cleanup doesn't cancel any future stop invocations.
    private val cleanupScope = kotlinx.coroutines.CoroutineScope(
        Dispatchers.IO + SupervisorJob(),
    )

    private suspend fun maybeAlert(mps: Float, limitKmh: Float?) {
        val speedKmh = SpeedUnit.KmH.fromMetersPerSecond(mps)
        val rising = shouldAlertOnCrossing(wasOverLimit, speedKmh, limitKmh)
        wasOverLimit = limitKmh != null && speedKmh > limitKmh
        if (rising && settings.alertOnOverLimit.first()) {
            alertPlayer.alert()
        }
    }
}
