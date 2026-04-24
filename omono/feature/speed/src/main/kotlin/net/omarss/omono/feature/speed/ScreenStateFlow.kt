package net.omarss.omono.feature.speed

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.PowerManager
import androidx.core.content.ContextCompat
import androidx.core.content.getSystemService
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

// Cold Flow<Boolean> that emits true when the device's screen is on,
// false when it's off. Seeded from PowerManager.isInteractive so the
// first emission is correct — without seeding, the flow would sit at
// its initial value until the first screen transition and the
// distraction guard would miss a drive that began with the screen
// already on.
//
// Uses receiver-not-exported in case a future AGP runs the app on a
// version that defaults to exported-required; SCREEN_ON/OFF are
// protected system broadcasts and can't originate from other apps
// anyway, but the explicit flag quiets the lint warning.
fun Context.screenOnFlow(): Flow<Boolean> = callbackFlow {
    val pm = getSystemService<PowerManager>()
    trySend(pm?.isInteractive == true)

    val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                Intent.ACTION_SCREEN_ON -> trySend(true)
                Intent.ACTION_SCREEN_OFF -> trySend(false)
            }
        }
    }
    val filter = IntentFilter().apply {
        addAction(Intent.ACTION_SCREEN_ON)
        addAction(Intent.ACTION_SCREEN_OFF)
    }
    // Apps targeting API 34+ must declare whether a context-registered
    // receiver is exported. SCREEN_ON/OFF are protected system
    // broadcasts (exempt today) but we flag explicitly so a future
    // lint/target-SDK bump doesn't silently start crashing here.
    ContextCompat.registerReceiver(
        this@screenOnFlow,
        receiver,
        filter,
        ContextCompat.RECEIVER_NOT_EXPORTED,
    )

    awaitClose { runCatching { unregisterReceiver(receiver) } }
}
