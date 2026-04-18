package net.omarss.omono.permissions

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import net.omarss.omono.core.data.omonoDataStore
import javax.inject.Inject
import javax.inject.Singleton

// Android can revoke runtime permissions silently: the system "auto-revoke
// unused permissions" feature kicks in after months of inactivity, and
// users sometimes explicitly toggle a permission off in system Settings
// and forget. When that happens to omono the affected feature goes quiet
// (no more SMS parsing, no more GPS samples) with zero UI feedback.
//
// This tracker records a one-way "ever granted" flag per permission. The
// UI compares it against the current runtime state on every resume, and
// surfaces a banner when something that used to work has been revoked.
// The flag is never cleared — a previously-granted permission that's now
// missing is *always* a regression worth flagging, even across restarts.
//
// Scope is deliberately limited to the four permissions whose loss
// silently breaks a core feature: SMS (no spending), fine location (no
// speed), notifications (no alerts visible), usage stats (no nav-app
// whitelist for the distraction guard). Battery / DND / Shizuku already
// surface their own state in dedicated cards.
enum class TrackedPermission(internal val storageKey: String, val label: String) {
    SMS(storageKey = "perm.ever_granted.sms", label = "Read SMS"),
    LOCATION(storageKey = "perm.ever_granted.location", label = "Location"),
    NOTIFICATIONS(storageKey = "perm.ever_granted.notifications", label = "Notifications"),
    USAGE_STATS(storageKey = "perm.ever_granted.usage_stats", label = "Usage access"),
}

@Singleton
class PermissionBaselineTracker @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    // Per-permission "has this ever been granted" flag. Reads as false
    // until the first time recordCurrent sees the permission granted,
    // then flips to true and stays there.
    val everGranted: Flow<Map<TrackedPermission, Boolean>> =
        context.omonoDataStore.data.map { prefs ->
            TrackedPermission.entries.associateWith { perm ->
                prefs[booleanPreferencesKey(perm.storageKey)] ?: false
            }
        }

    // Writes true once per permission when the UI reports it granted.
    // Idempotent — a quick no-op via DataStore's edit coalescing once
    // the value is already true.
    suspend fun recordCurrent(states: Map<TrackedPermission, Boolean>) {
        context.omonoDataStore.edit { prefs ->
            states.forEach { (perm, granted) ->
                if (granted) {
                    val key = booleanPreferencesKey(perm.storageKey)
                    if (prefs[key] != true) prefs[key] = true
                }
            }
        }
    }
}
