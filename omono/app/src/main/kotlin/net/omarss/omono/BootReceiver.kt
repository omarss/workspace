package net.omarss.omono

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat
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

        // Prayer alarms restore independently from saved coordinates. Do not
        // crash their shared process by starting a location FGS without the
        // background access Android requires at boot.
        val hasLocation = listOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
            .any { ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED }
        val hasBackground = Build.VERSION.SDK_INT < 29 || ContextCompat.checkSelfPermission(
            context, Manifest.permission.ACCESS_BACKGROUND_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED
        if (!hasLocation || !hasBackground) {
            Timber.w("Boot tracking skipped: background location unavailable; prayer alarms restore separately")
            return
        }
        runCatching { FeatureHostService.start(context) }
            .onFailure { Timber.e(it, "Boot tracking start was refused") }
    }
}
