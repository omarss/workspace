package net.omarss.omono.core.notification

// Central registry of notification channels. Features declare one here
// so the channel ID is stable and visible across the whole app.
object OmonoNotificationChannels {
    const val FEATURE_HOST_CHANNEL_ID: String = "omono.feature_host"
    const val FEATURE_HOST_CHANNEL_NAME: String = "Background trackers"

    const val SELF_UPDATE_CHANNEL_ID: String = "omono.self_update"
    const val SELF_UPDATE_CHANNEL_NAME: String = "App updates"
}
