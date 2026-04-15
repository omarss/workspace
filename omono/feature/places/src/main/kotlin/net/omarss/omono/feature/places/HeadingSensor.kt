package net.omarss.omono.feature.places

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import javax.inject.Inject
import javax.inject.Singleton

// Device compass heading in degrees, 0° = true north, clockwise. Hot
// flow that registers / unregisters the sensor listener on subscribe
// to save battery when the places screen isn't visible.
//
// TYPE_ROTATION_VECTOR is the modern replacement for the older
// accelerometer+magnetometer dance — it delivers a quaternion that
// Android's SensorManager converts into a rotation matrix, from which
// we pull the first Euler angle (azimuth). Low-pass smoothing removes
// the jitter that would otherwise make the UI unreadable.
@Singleton
class HeadingSensor @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    fun headings(): Flow<Float> = callbackFlow {
        val manager = context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
        val sensor = manager?.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
        if (manager == null || sensor == null) {
            // No rotation vector sensor on this device (rare). Emit a
            // single 0° reading and close so the UI stops spinning.
            trySend(0f)
            close()
            return@callbackFlow
        }

        val rotationMatrix = FloatArray(9)
        val orientation = FloatArray(3)
        var smoothed = Float.NaN

        val listener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent) {
                SensorManager.getRotationMatrixFromVector(rotationMatrix, event.values)
                SensorManager.getOrientation(rotationMatrix, orientation)
                val rawDeg = ((Math.toDegrees(orientation[0].toDouble()) + 360.0) % 360.0).toFloat()
                // Low-pass filter with circular (wrap-around) handling
                // so e.g. smoothing 359° → 1° doesn't crash through 180°.
                smoothed = if (smoothed.isNaN()) {
                    rawDeg
                } else {
                    circularLowPass(smoothed, rawDeg, SMOOTHING)
                }
                trySend(smoothed)
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
        }

        manager.registerListener(listener, sensor, SensorManager.SENSOR_DELAY_UI)
        awaitClose { manager.unregisterListener(listener) }
    }

    private companion object {
        const val SMOOTHING: Float = 0.15f
    }
}

internal fun circularLowPass(previous: Float, current: Float, alpha: Float): Float {
    var delta = current - previous
    if (delta > 180f) delta -= 360f
    if (delta < -180f) delta += 360f
    val next = previous + alpha * delta
    return ((next + 360f) % 360f)
}
