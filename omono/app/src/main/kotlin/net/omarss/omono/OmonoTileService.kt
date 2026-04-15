package net.omarss.omono

import android.graphics.drawable.Icon
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import dagger.hilt.android.AndroidEntryPoint
import net.omarss.omono.core.notification.R as NotificationR
import net.omarss.omono.core.service.FeatureHostService
import net.omarss.omono.core.service.FeatureHostStateHolder
import javax.inject.Inject

// Exposes omono's start/stop toggle as a Quick Settings tile so the
// most common action is reachable from the system pull-down without
// opening the app.
//
// Mechanics: onClick() reads the shared FeatureHostStateHolder to
// decide whether to start or stop the foreground service, then
// repaints the tile. onStartListening() is fired by the platform
// whenever the user expands the Quick Settings panel — we re-read
// the state holder there too so the tile reflects state changes that
// happened while the panel was closed (e.g. an in-app Stop tap).
@AndroidEntryPoint
class OmonoTileService : TileService() {

    @Inject lateinit var stateHolder: FeatureHostStateHolder

    override fun onStartListening() {
        super.onStartListening()
        updateTile()
    }

    override fun onClick() {
        super.onClick()
        val ctx = applicationContext
        if (stateHolder.running.value) {
            FeatureHostService.stop(ctx)
        } else {
            FeatureHostService.start(ctx)
        }
        updateTile()
    }

    private fun updateTile() {
        val tile = qsTile ?: return
        val running = stateHolder.running.value
        tile.state = if (running) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
        tile.label = "omono"
        tile.contentDescription = if (running) "Stop tracking" else "Start tracking"
        // Tile.setSubtitle is API 29+; minSdk is 26 so guard.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            tile.subtitle = if (running) "Tracking" else "Tap to start"
        }
        tile.icon = Icon.createWithResource(this, NotificationR.drawable.ic_notification_small)
        tile.updateTile()
    }
}
