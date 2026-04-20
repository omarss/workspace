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

// "Is the phone moving at all right now?" — derived from the
// variance of the accelerometer magnitude over a short rolling
// window.
//
// Threshold is intentionally very low (0.05 m²/s⁴) so it only
// classifies "dead still" — a phone left flat on a passenger seat,
// cup-holder, or dashboard in a stopped car. A phone that's
// dashboard-mounted in a moving car picks up road vibration
// (typical 0.05–0.15) which stays above this floor, so the user's
// scroll-while-driving case still reads as "active" and the
// distraction beep fires. Holding the phone in-hand picks up
// dominant variance > 0.5, which is emphatically "active".
//
// The guard uses this as a hold-off: if the phone stays below the
// floor for `STILL_HOLD_MS`, we stop beeping until the next time
// the phone moves (picked up / car shakes over a speed bump).
// Returns `true` when the phone has registered *any* motion within
// the hold window, `false` only after a prolonged quiet.
//
// Emits only on state transitions (not on every 20 Hz sample) so the
// downstream combine doesn't thrash. Defaults to `true` (active) on
// devices without an accelerometer so the guard behaves as before.
fun Context.phoneInHandFlow(): Flow<Boolean> = callbackFlow {
    val sensorManager = getSystemService<android.hardware.SensorManager>()
    val accel = sensorManager?.getDefaultSensor(android.hardware.Sensor.TYPE_ACCELEROMETER)
    if (sensorManager == null || accel == null) {
        trySend(true) // no sensor — never silence on "not held"
        awaitClose { }
        return@callbackFlow
    }
    trySend(true) // initial assumption: held, until we've sampled

    val window = ArrayDeque<Float>()
    var lastEmitted: Boolean? = null
    var lastActiveMs = System.currentTimeMillis()

    val listener = object : android.hardware.SensorEventListener {
        override fun onSensorChanged(event: android.hardware.SensorEvent) {
            val v = event.values
            if (v.size < 3) return
            val magnitude = kotlin.math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
            window.addLast(magnitude)
            while (window.size > WINDOW_SIZE) window.removeFirst()
            if (window.size < WINDOW_SIZE) return
            // Population variance is fine — the window is fixed-size.
            val mean = window.sum() / window.size
            var ss = 0.0
            window.forEach { ss += (it - mean) * (it - mean) }
            val variance = ss / window.size
            val now = System.currentTimeMillis()
            if (variance > STILL_VARIANCE_THRESHOLD) {
                lastActiveMs = now
            }
            // Emit "active" while we've seen motion within the hold
            // window — catches road vibration keeping a mounted
            // phone "active" across a brief between-bumps lull, and
            // releases to "still" only after prolonged quiet (phone
            // put down on a flat surface).
            val active = (now - lastActiveMs) < STILL_HOLD_MS
            if (active != lastEmitted) {
                lastEmitted = active
                trySend(active)
            }
        }
        override fun onAccuracyChanged(s: android.hardware.Sensor?, a: Int) = Unit
    }
    // SENSOR_DELAY_UI is ~60 ms — roughly 16 Hz, plenty for a 1 s
    // window and cheap on power compared to GAME or FASTEST.
    sensorManager.registerListener(listener, accel, android.hardware.SensorManager.SENSOR_DELAY_UI)
    awaitClose { runCatching { sensorManager.unregisterListener(listener) } }
}

private const val IN_CALL_POLL_MS: Long = 2_000L

// ~1 s of samples at SENSOR_DELAY_UI. Long enough to average out a
// single bump, short enough that picking up the phone registers
// within one second.
private const val WINDOW_SIZE: Int = 16

// Very low threshold — we only want to classify "dead still" as
// stationary. A phone dashboard-mounted in a moving car picks up
// enough road vibration to clear this floor even at urban crawl
// speeds; a phone left flat on a seat in a stopped car does not.
private const val STILL_VARIANCE_THRESHOLD: Double = 0.05

// Hold window — keep reporting "active" for this long after the
// last above-threshold sample. Covers the between-bump lull on
// very smooth roads / in a well-suspended vehicle. After the
// window expires with no motion the guard de-arms and beeping
// stops; the next bump or pickup re-arms within a sample (~60 ms).
private const val STILL_HOLD_MS: Long = 8_000L
