package net.omarss.omono.feature.speed

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.os.Process
import androidx.core.content.getSystemService
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

// Reads the "which app is currently in the foreground" signal from
// UsageStatsManager. Used by the distraction guard to distinguish
// "driver has navigation open" (legitimate) from "driver scrolling
// Instagram" (what we want to discourage).
//
// Android makes this a special permission — PACKAGE_USAGE_STATS
// isn't grantable via the normal runtime prompt; the user has to
// flip it in Settings → Apps → Special access. We surface the
// permission state so the UI can offer the right nudge.
@Singleton
class ForegroundAppDetector @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    private val usageStatsManager = context.getSystemService<UsageStatsManager>()

    // AppOps-based check — the usual pattern for PACKAGE_USAGE_STATS
    // because a plain checkPermission() always returns denied for
    // this perm regardless of actual state. The non-"unsafe" variant
    // is deprecated on API 29+ but still works and stays available
    // back to API 19, so it fits the minSdk=26 baseline without a
    // version branch.
    @Suppress("DEPRECATION")
    fun hasUsageStatsPermission(): Boolean {
        val appOps = context.getSystemService<AppOpsManager>() ?: return false
        val mode = runCatching {
            appOps.checkOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(),
                context.packageName,
            )
        }.getOrElse { return false }
        return mode == AppOpsManager.MODE_ALLOWED
    }

    // Returns the package name of whichever app was most recently
    // brought to the foreground inside the last ~10 s. Null when the
    // permission isn't granted or nothing's been opened recently.
    fun currentForegroundPackage(nowMs: Long = System.currentTimeMillis()): String? {
        val mgr = usageStatsManager ?: return null
        if (!hasUsageStatsPermission()) return null
        val events = runCatching { mgr.queryEvents(nowMs - LOOKBACK_MS, nowMs) }
            .getOrNull() ?: return null
        var lastFgPackage: String? = null
        val event = UsageEvents.Event()
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            val type = event.eventType
            if (type == UsageEvents.Event.MOVE_TO_FOREGROUND ||
                type == UsageEvents.Event.ACTIVITY_RESUMED
            ) {
                lastFgPackage = event.packageName
            }
        }
        return lastFgPackage
    }

    // Rough "is this a navigation app?" filter. Used by the guard to
    // pause beeping when the driver has maps open. Conservative — only
    // the apps users actually drive with in KSA are whitelisted; other
    // non-driving apps still trigger the alert.
    fun isNavigationApp(packageName: String?): Boolean =
        packageName != null && packageName in NAV_APPS

    private companion object {
        const val LOOKBACK_MS = 10_000L

        // Explicitly the driver-routing apps, not every map app. The
        // user's "no phone while driving" setting means "don't do
        // anything non-driving"; Google Earth, for example, is not
        // included on purpose.
        val NAV_APPS = setOf(
            "com.google.android.apps.maps", // Google Maps
            "com.waze",                      // Waze
            "com.yandex.yango",              // Yango (Yandex for MENA)
            "com.yandex.yandexmaps",         // Yandex Maps
            "ru.yandex.yandexnavi",          // Yandex Navigator
            "com.tomtom.gplay.navapp",       // TomTom Go Navigation
            "com.here.app.maps",             // HERE WeGo
            "net.omarss.omono",              // omono itself
            "net.omarss.omono.debug",        // omono debug variant
        )
    }
}
