package net.omarss.omono.feature.speed

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.media.AudioManager
import androidx.core.content.getSystemService
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flow

// Flows that suppress the distraction guard and the over-limit alert
// when the driver is either on a phone call (don't step on the call
// audio) or has set the phone down (proximity sensor covered — face-
// down on the dashboard, slipped into a pocket, etc.). Both are opt-
// out-at-the-signal rather than settings because disabling them would
// defeat their purpose.

// Proximity-covered as a hot boolean. True when the sensor reads a
// value below its `maximumRange`, meaning something is close (< a few
// cm). Emits `false` on devices without a proximity sensor so the
// guard behaves as before on older hardware.
fun Context.proximityCoveredFlow(): Flow<Boolean> = callbackFlow {
    val sensorManager = getSystemService<SensorManager>()
    val proximity = sensorManager?.getDefaultSensor(Sensor.TYPE_PROXIMITY)
    if (sensorManager == null || proximity == null) {
        trySend(false)
        awaitClose { }
        return@callbackFlow
    }
    // Initial emission until the sensor reports. Assume uncovered —
    // otherwise a phone held in-hand but with a recently-unregistered
    // listener would start out covered and suppress alerts.
    trySend(false)

    val listener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            val value = event.values.firstOrNull() ?: return
            // Maximum range is the sensor's "far" reading; anything less
            // means something's nearby. A handful of phones report only
            // 0/1 binary values — still below maximumRange when close.
            trySend(value < proximity.maximumRange)
        }
        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
    }
    sensorManager.registerListener(listener, proximity, SensorManager.SENSOR_DELAY_UI)
    awaitClose { runCatching { sensorManager.unregisterListener(listener) } }
}

// In-call state via AudioManager.mode. Polled every 2 s — a finer-
// grained callback API (AudioManager.OnModeChangedListener) only
// landed on API 31, and omono's minSdk is 26. 2 s is fast enough
// that an incoming call silences the next beep burst well before a
// user tries to accept it.
fun Context.inCallFlow(): Flow<Boolean> = flow {
    val audioManager = getSystemService<AudioManager>()
    while (true) {
        val mode = audioManager?.mode ?: AudioManager.MODE_NORMAL
        emit(mode == AudioManager.MODE_IN_CALL || mode == AudioManager.MODE_IN_COMMUNICATION)
        delay(IN_CALL_POLL_MS)
    }
}

private const val IN_CALL_POLL_MS: Long = 2_000L
