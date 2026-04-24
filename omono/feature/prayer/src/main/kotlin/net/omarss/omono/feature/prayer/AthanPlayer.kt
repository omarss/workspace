package net.omarss.omono.feature.prayer

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.OpenableColumns
import androidx.core.content.getSystemService
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

// Source of an athan playable by the prayer alarm. Bundled items
// live inside the APK's assets — always present, never deletable.
// Local items live under the app's external files directory and are
// added by the user via the SAF picker.
sealed interface AthanItem {
    val displayName: String
    // Stable string that uniquely identifies this item across the
    // bundled + local pools. Persisted in PrayerSettings so a
    // pinned selection survives restarts.
    val identifier: String

    // Optional per-item attribution. Rendered inline when the user
    // has a CC-BY-SA file selected — legally required by the
    // license and nice-to-have for the public-domain ones too.
    val credit: String?

    data class Bundled(
        val assetPath: String,
        override val credit: String? = null,
    ) : AthanItem {
        override val displayName: String
            get() = assetPath.substringAfterLast('/').substringBeforeLast('.')
                .replace('_', ' ')
                .replaceFirstChar { it.titlecase() }
                .trim()
        override val identifier: String get() = "bundled:$assetPath"
    }

    data class Local(val file: File) : AthanItem {
        override val displayName: String get() = file.nameWithoutExtension
        override val identifier: String get() = "local:${file.name}"
        override val credit: String? get() = null
    }
}

// Plays the athan at Fajr. Sources come from two places:
//   * Bundled assets — assets/athans/*.mp3 shipped in the APK. Six
//     public-domain recordings seed day-one usage.
//   * Local files — whatever the user has imported via SAF. Copied
//     into the app's external files dir on import.
//
// Playback runs through STREAM_ALARM with USAGE_ALARM so it bypasses
// silent mode and fires even during Doze. Volume ramps up from
// ~10% to 100% over FADE_DURATION_MS so the user isn't jolted awake
// by a sudden full-blast call; the same ramp is what every well-
// designed alarm clock does.
@Singleton
class AthanPlayer @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    @Volatile private var current: MediaPlayer? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private var fadeRunnable: Runnable? = null

    // Saved volume for STREAM_ALARM so we can restore after playback.
    // The alarm volume is maxed while the athan plays so the user
    // hears it at the loudest the device allows, even if they'd
    // dialled STREAM_ALARM down the night before.
    private var savedStreamVolume: Int? = null

    // Returns the external dir where user-imported athans live.
    // Created on demand. The UI uses this to show the user where
    // added files physically land on disk.
    fun athansDirectory(): File {
        val dir = File(context.getExternalFilesDir(null), DIRECTORY_NAME)
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    // Full pool of playable items = bundled assets + user-imported.
    // Bundled always first so the list order in the UI is stable.
    fun availableAthans(): List<AthanItem> {
        val bundled = runCatching {
            context.assets.list(BUNDLED_DIR)?.toList().orEmpty()
                .filter { name ->
                    val ext = name.substringAfterLast('.', "").lowercase()
                    ext in SUPPORTED_EXTS
                }
                .sorted()
                .map { name ->
                    AthanItem.Bundled(
                        assetPath = "$BUNDLED_DIR/$name",
                        credit = BUNDLED_CREDITS[name],
                    )
                }
        }.onFailure { Timber.w(it, "AthanPlayer: listing bundled assets failed") }
            .getOrNull().orEmpty()
        val local = availableLocalFiles().map { AthanItem.Local(it) }
        return bundled + local
    }

    // Kept for the delete path in the ViewModel — the picker in
    // Settings only lets the user delete *local* files, so we need
    // to enumerate them independently of the bundled set.
    fun availableLocalFiles(): List<File> {
        return athansDirectory().listFiles { f -> f.isFile && f.isReadableAudio() }
            ?.toList().orEmpty().sortedBy { it.name }
    }

    // Plays the selected item (or a random one from the pool) with
    // a gradual volume ramp. Returns true if playback started
    // successfully (bundled / local file OR the system default alarm
    // sound when the pool is empty).
    fun play(selection: AthanSelection = AthanSelection.Random): Boolean {
        stop()
        val pool = availableAthans()
        val chosen: AthanItem? = when {
            pool.isEmpty() -> null
            selection is AthanSelection.Specific ->
                pool.firstOrNull { it.identifier == selection.fileName } ?: pool.random()
            else -> pool.random()
        }
        snapshotAndMaxAlarmVolume()
        val player = if (chosen != null) {
            Timber.i("AthanPlayer: playing %s", chosen.identifier)
            when (chosen) {
                is AthanItem.Bundled -> startFromAsset(chosen.assetPath)
                is AthanItem.Local -> startFromFile(chosen.file)
            } ?: startFromDefault()
        } else {
            Timber.i("AthanPlayer: pool empty, falling back to default alarm sound")
            startFromDefault()
        }
        current = player
        if (player != null) startFadeIn(player) else restoreAlarmVolume()
        return player != null
    }

    @Deprecated(
        "Use play(AthanSelection) directly; kept for call-site compatibility.",
        ReplaceWith("play(AthanSelection.Random)"),
    )
    fun playRandom(): Boolean = play(AthanSelection.Random)

    fun stop() {
        cancelFade()
        current?.let { mp ->
            runCatching {
                if (mp.isPlaying) mp.stop()
                mp.release()
            }
        }
        current = null
        restoreAlarmVolume()
    }

    // Copies the content behind a SAF uri (ACTION_OPEN_DOCUMENT
    // result) into the local athans directory.
    fun importFromUri(uri: Uri): File? {
        val name = queryDisplayName(uri) ?: "athan-${System.currentTimeMillis()}.mp3"
        val target = File(athansDirectory(), sanitizeFileName(name))
        return runCatching {
            context.contentResolver.openInputStream(uri).use { input ->
                if (input == null) error("could not open uri")
                target.outputStream().use { output -> input.copyTo(output) }
            }
            target
        }.onFailure {
            Timber.w(it, "AthanPlayer: import failed for %s", uri)
            target.delete()
        }.getOrNull()
    }

    // Only local files are deletable. Bundled items silently ignore.
    fun deleteAthan(file: File): Boolean {
        if (!file.exists()) return false
        val withinDir = try {
            file.canonicalPath.startsWith(athansDirectory().canonicalPath)
        } catch (_: Exception) {
            false
        }
        if (!withinDir) {
            Timber.w("AthanPlayer: refusing to delete outside athans dir: %s", file)
            return false
        }
        return runCatching { file.delete() }.getOrDefault(false)
    }

    // ------------------------------------------------------------------

    private fun startFromAsset(assetPath: String): MediaPlayer? {
        val afd = runCatching { context.assets.openFd(assetPath) }
            .onFailure { Timber.w(it, "AthanPlayer: openFd failed for %s", assetPath) }
            .getOrNull() ?: return null
        return runCatching {
            MediaPlayer().apply {
                applyAlarmAudioAttributes()
                setDataSource(afd.fileDescriptor, afd.startOffset, afd.length)
                afd.close()
                setOnCompletionListener { runCatching { release() } }
                setOnErrorListener { _, _, _ -> runCatching { release() }; true }
                prepare()
                // Start at fade-from volume so the first audible
                // sample lands quietly, not at full-blast.
                setVolume(FADE_START_VOLUME, FADE_START_VOLUME)
                start()
            }
        }.onFailure {
            Timber.w(it, "AthanPlayer: failed to play asset %s", assetPath)
            runCatching { afd.close() }
        }.getOrNull()
    }

    private fun startFromFile(file: File): MediaPlayer? = runCatching {
        MediaPlayer().apply {
            applyAlarmAudioAttributes()
            setDataSource(file.absolutePath)
            setOnCompletionListener { runCatching { release() } }
            setOnErrorListener { _, _, _ -> runCatching { release() }; true }
            prepare()
            setVolume(FADE_START_VOLUME, FADE_START_VOLUME)
            start()
        }
    }.onFailure { Timber.w(it, "AthanPlayer: failed to play %s", file.name) }.getOrNull()

    private fun startFromDefault(): MediaPlayer? {
        val uri: Uri = RingtoneManager.getActualDefaultRingtoneUri(
            context, RingtoneManager.TYPE_ALARM,
        ) ?: RingtoneManager.getActualDefaultRingtoneUri(
            context, RingtoneManager.TYPE_NOTIFICATION,
        ) ?: return null
        return runCatching {
            MediaPlayer().apply {
                applyAlarmAudioAttributes()
                setDataSource(context, uri)
                setOnCompletionListener { runCatching { release() } }
                setOnErrorListener { _, _, _ -> runCatching { release() }; true }
                prepare()
                setVolume(FADE_START_VOLUME, FADE_START_VOLUME)
                start()
            }
        }.onFailure { Timber.w(it, "AthanPlayer: default sound fallback failed") }.getOrNull()
    }

    private fun MediaPlayer.applyAlarmAudioAttributes() {
        setAudioAttributes(
            AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build(),
        )
    }

    // Snapshot the user's current STREAM_ALARM setting and raise it
    // to max for the athan. Restored by restoreAlarmVolume() once
    // playback ends or the user taps stop. Wrapped in runCatching
    // because OEMs can refuse the raise on locked profiles.
    private fun snapshotAndMaxAlarmVolume() {
        val am = context.getSystemService<AudioManager>() ?: return
        if (savedStreamVolume != null) return // already elevated
        runCatching {
            savedStreamVolume = am.getStreamVolume(AudioManager.STREAM_ALARM)
            val max = am.getStreamMaxVolume(AudioManager.STREAM_ALARM)
            am.setStreamVolume(AudioManager.STREAM_ALARM, max, 0)
        }.onFailure { Timber.w(it, "AthanPlayer: raising STREAM_ALARM failed") }
    }

    private fun restoreAlarmVolume() {
        val am = context.getSystemService<AudioManager>() ?: return
        val saved = savedStreamVolume ?: return
        runCatching { am.setStreamVolume(AudioManager.STREAM_ALARM, saved, 0) }
        savedStreamVolume = null
    }

    // Gradual linear ramp from FADE_START_VOLUME to 1.0 over
    // FADE_DURATION_MS. Driven off a Handler rather than a coroutine
    // so it keeps ticking even while the process is nominally asleep
    // — MediaPlayer.setVolume is thread-safe and cheap.
    private fun startFadeIn(player: MediaPlayer) {
        cancelFade()
        val totalSteps = FADE_STEPS
        val perStepMs = FADE_DURATION_MS / totalSteps
        val perStepDelta = (1f - FADE_START_VOLUME) / totalSteps
        var step = 0
        val runnable = object : Runnable {
            override fun run() {
                step++
                val vol = (FADE_START_VOLUME + perStepDelta * step).coerceAtMost(1f)
                runCatching { player.setVolume(vol, vol) }
                if (step < totalSteps && current === player) {
                    mainHandler.postDelayed(this, perStepMs.toLong())
                }
            }
        }
        fadeRunnable = runnable
        mainHandler.postDelayed(runnable, perStepMs.toLong())
    }

    private fun cancelFade() {
        fadeRunnable?.let { mainHandler.removeCallbacks(it) }
        fadeRunnable = null
    }

    private fun queryDisplayName(uri: Uri): String? = runCatching {
        context.contentResolver.query(
            uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null,
        )?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0) else null
        }
    }.getOrNull()

    private fun sanitizeFileName(name: String): String {
        val cleaned = name.replace(Regex("[^A-Za-z0-9._\\- ]+"), "_").trim()
        return cleaned.ifEmpty { "athan.mp3" }
    }

    private fun File.isReadableAudio(): Boolean =
        extension.lowercase() in SUPPORTED_EXTS

    private companion object {
        const val DIRECTORY_NAME = "athans"
        const val BUNDLED_DIR = "athans"
        val SUPPORTED_EXTS = setOf("mp3", "ogg", "oga", "m4a", "aac", "wav", "flac", "opus")

        // Fade parameters. 15 s from 10% to 100% is the same ramp
        // most gentle-wake alarm clocks use — long enough to avoid
        // startling, short enough that a heavy sleeper still gets
        // blasted awake by Fajr.
        const val FADE_START_VOLUME: Float = 0.10f
        const val FADE_DURATION_MS: Long = 15_000L
        const val FADE_STEPS: Int = 60

        // Per-file attribution metadata for the bundled set. Keys
        // are asset filenames inside BUNDLED_DIR; values render
        // under the file row in the picker. Public-domain entries
        // are kept brief; CC-BY-SA entries include the author and
        // license name so the legally-required attribution is
        // satisfied purely by having the picker open.
        val BUNDLED_CREDITS: Map<String, String> = mapOf(
            "doha_fajr.mp3" to "Fajr adhan · Doha, Qatar · Public Domain",
            "doha_dhuhr.mp3" to "Dhuhr adhan · Doha, Qatar · Public Domain",
            "doha_asr.mp3" to "Asr adhan · Doha, Qatar · Public Domain",
            "doha_maghrib.mp3" to "Maghrib adhan · Doha, Qatar · Public Domain",
            "doha_isha.mp3" to "Isha adhan · Doha, Qatar · Public Domain",
            "sabah_fakhri.mp3" to "Sabah Fakhri (1985) · Public Domain",
            "aaqib_azeez.mp3" to "Aaqib Azeez · CC-BY-SA 4.0",
            "mahfoudou.oga" to "Mahfoudou · CC-BY-SA 4.0",
        )
    }
}
