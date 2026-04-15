package net.omarss.omono.ui

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.provider.Settings
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

// Tracks whether the app has been granted "Do Not Disturb access". The
// user has to turn this on in a dedicated system settings page; there's
// no runtime permission dialog for it. We observe ON_RESUME so the UI
// updates the moment the user comes back from the settings screen.
@Composable
fun rememberNotificationPolicyAccessState(): State<Boolean> {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val state = remember { mutableStateOf(isNotificationPolicyAccessGranted(context)) }
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                state.value = isNotificationPolicyAccessGranted(context)
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    return state
}

fun isNotificationPolicyAccessGranted(context: Context): Boolean {
    val nm = context.getSystemService(NotificationManager::class.java) ?: return false
    return nm.isNotificationPolicyAccessGranted
}

// Deep-links to the system "Do Not Disturb access" settings page where
// the user can toggle the per-app switch. No programmatic grant exists.
fun launchNotificationPolicyAccessSettings(context: Context) {
    val intent = Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { context.startActivity(intent) }
        .onFailure {
            // Fallback: some ROMs ship without the dedicated page; open
            // generic sound/DND settings instead.
            runCatching {
                context.startActivity(
                    Intent(Settings.ACTION_SOUND_SETTINGS)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                )
            }
        }
}
