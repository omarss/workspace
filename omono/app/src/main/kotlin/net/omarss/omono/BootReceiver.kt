package net.omarss.omono

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import net.omarss.omono.core.service.FeatureHostService
import timber.log.Timber

// Re-launch the host service after a reboot so background trackers come
// back up automatically. Registered statically in the manifest because
// runtime registration would never fire — the app isn't running yet.
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED &&
            intent.action != Intent.ACTION_LOCKED_BOOT_COMPLETED
        ) return

        Timber.i("Boot completed — starting FeatureHostService")
        FeatureHostService.start(context)
    }
}
