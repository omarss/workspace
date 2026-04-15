package net.omarss.omono.feature.selfupdate

// One published release as described in /manifest.json on the apps host.
// Mirrors the schema the publish script writes — we only surface the
// fields the updater actually consumes.
data class Release(
    val version: String,
    val apkFileName: String,
    val sizeBytes: Long,
    val sha256: String,
    val changelog: List<String>,
    val releasedAt: String,
)

// The "is there a newer build than me?" answer surfaced to the UI.
// `cumulativeChangelog` stitches together every release strictly newer
// than the one currently installed — handy when the user skipped a few.
data class UpdateInfo(
    val latest: Release,
    val cumulativeChangelog: List<String>,
    val apkUrl: String,
)
