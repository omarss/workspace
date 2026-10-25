package net.omarss.omono.feature.prayer

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.AudioFocusRequest
import android.media.AudioDeviceInfo
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.net.Uri
import android.os.PowerManager
import android.os.Build
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

// Uses the alarm stream at maximum volume immediately. A foreground service
// owns scheduled playback; the player holds a CPU wake lock while sounding.
@Singleton
class AthanPlayer @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    @Volatile private var current: MediaPlayer? = null
    private var finished: ((String) -> Unit)? = null
    private var fallbackUsed = false
    private var focusRequest: AudioFocusRequest? = null
    val isPlaying: Boolean get() = runCatching { current?.isPlaying == true }.getOrDefault(false)

    // Saved volume for STREAM_ALARM so we can restore after playback.
    // The alarm volume is maxed while the athan plays so the user
    // hears it at the loudest the device allows, even if they'd
    // dialled STREAM_ALARM down the night before.
    private var savedStreamVolume: Int? = null
    private var savedStreamMuted: Boolean? = null

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
    // maximum alarm volume. Returns true if playback started
    // successfully (bundled / local file OR the system default alarm
    // sound when the pool is empty).
    fun play(selection: AthanSelection = AthanSelection.Random, onFinished: ((String) -> Unit)? = null): Boolean {
        stop()
        fallbackUsed = false
        val pool = availableAthans()
        val chosen: AthanItem? = when {
            pool.isEmpty() -> null
            selection is AthanSelection.Specific ->
                pool.firstOrNull { it.identifier == selection.fileName } ?: pool.random()
            else -> pool.random()
        }
        snapshotAndMaxAlarmVolume()
        requestAlarmFocus()
        finished = onFinished
        val player = if (chosen != null) {
            Timber.i("AthanPlayer: playing %s", chosen.identifier)
            when (chosen) {
                is AthanItem.Bundled -> startFromAsset(chosen.assetPath)
                is AthanItem.Local -> startFromFile(chosen.file)
            } ?: startFallback()
        } else {
            Timber.i("AthanPlayer: pool empty, falling back to default alarm sound")
            startFallback()
        }
        current = player
        if (player == null) {
            restoreAlarmVolume()
            abandonAlarmFocus()
            finished = null
        }
        return player != null
    }

    @Deprecated(
        "Use play(AthanSelection) directly; kept for call-site compatibility.",
        ReplaceWith("play(AthanSelection.Random)"),
    )
    fun playRandom(): Boolean = play(AthanSelection.Random)

    fun stop() {
        val player = current
        current = null
        player?.let { runCatching { it.stop() }; runCatching { it.release() } }
        restoreAlarmVolume()
        abandonAlarmFocus()
        val callback = finished
        finished = null
        callback?.invoke("Stopped")
    }

    private fun finishPlayback(player: MediaPlayer, status: String) {
        if (current !== player) return
        current = null
        runCatching { player.release() }
        restoreAlarmVolume()
        abandonAlarmFocus()
        val callback = finished
        finished = null
        callback?.invoke(status)
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

    private fun startFromAsset(assetPath: String): MediaPlayer? = runCatching {
        context.assets.openFd(assetPath).use { fd ->
            createPlayer { setDataSource(fd.fileDescriptor, fd.startOffset, fd.length) }
        }
    }.onFailure { Timber.e(it, "AthanPlayer: asset unavailable: %s", assetPath) }.getOrNull()

    private fun startFromFile(file: File): MediaPlayer? = createPlayer { setDataSource(file.absolutePath) }

    private fun startFallback(): MediaPlayer? {
        fallbackUsed = true
        return startFromDefault()
    }

    private fun startFromDefault(): MediaPlayer? {
        val uri = RingtoneManager.getActualDefaultRingtoneUri(context, RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
            ?: return null
        return createPlayer { setDataSource(context, uri) }
    }

    private fun alarmAttributes(): AudioAttributes = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_ALARM)
        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
        .build()

    private fun createPlayer(source: MediaPlayer.() -> Unit): MediaPlayer? {
        val player = MediaPlayer()
        return runCatching {
            player.apply {
                setAudioAttributes(alarmAttributes())
                setWakeMode(context, PowerManager.PARTIAL_WAKE_LOCK)
                source()
                setOnCompletionListener { finishPlayback(it, "Completed") }
                setOnErrorListener { failed, what, extra ->
                    if (current === failed && !fallbackUsed) {
                        Timber.e("AthanPlayer: decoder error %d/%d; trying default alarm", what, extra)
                        runCatching { failed.release() }
                        val fallback = startFallback()
                        if (fallback != null) {
                            current = fallback
                        } else finishPlayback(failed, "FAILED: audio error $what/$extra and default alarm unavailable")
                    } else finishPlayback(failed, "FAILED: audio error $what/$extra")
                    true
                }
                val speaker = context.getSystemService<AudioManager>()
                    ?.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
                    ?.firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
                if (Build.VERSION.SDK_INT >= 28 && speaker != null && !setPreferredDevice(speaker)) {
                    Timber.w("AthanPlayer: speaker routing preference refused")
                }
                prepare()
                setVolume(1f, 1f)
                start()
            }
        }.onFailure {
            Timber.e(it, "AthanPlayer: audio start failed")
            runCatching { player.release() }
        }.getOrNull()
    }

    private fun requestAlarmFocus() {
        val audio = context.getSystemService<AudioManager>() ?: return
        val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(alarmAttributes())
            .setOnAudioFocusChangeListener { change ->
                Timber.i("AthanPlayer: audio focus changed: %d", change)
            }
            .build()
        focusRequest = request
        if (audio.requestAudioFocus(request) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
            Timber.w("AthanPlayer: alarm audio focus not granted; verify sound with the timed test")
        }
    }

    private fun abandonAlarmFocus() {
        focusRequest?.let { request ->
            runCatching { context.getSystemService<AudioManager>()?.abandonAudioFocusRequest(request) }
        }
        focusRequest = null
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
            savedStreamMuted = am.isStreamMute(AudioManager.STREAM_ALARM)
            am.adjustStreamVolume(AudioManager.STREAM_ALARM, AudioManager.ADJUST_UNMUTE, 0)
            val max = am.getStreamMaxVolume(AudioManager.STREAM_ALARM)
            am.setStreamVolume(AudioManager.STREAM_ALARM, max, 0)
        }.onFailure { Timber.w(it, "AthanPlayer: raising STREAM_ALARM failed") }
    }

    // Other app features or volume controls may change the shared alarm
    // stream while sounding. Reassert loudness only while this player owns it.
    fun ensureLoudAlarm(): Boolean {
        if (!isPlaying) return false
        val audio = context.getSystemService<AudioManager>() ?: return false
        return runCatching {
            val max = audio.getStreamMaxVolume(AudioManager.STREAM_ALARM)
            if (audio.isStreamMute(AudioManager.STREAM_ALARM)) {
                audio.adjustStreamVolume(AudioManager.STREAM_ALARM, AudioManager.ADJUST_UNMUTE, 0)
            }
            if (audio.getStreamVolume(AudioManager.STREAM_ALARM) != max) {
                audio.setStreamVolume(AudioManager.STREAM_ALARM, max, 0)
            }
            audio.getStreamVolume(AudioManager.STREAM_ALARM) == max && !audio.isStreamMute(AudioManager.STREAM_ALARM)
        }.onFailure { Timber.e(it, "AthanPlayer: maintaining alarm volume failed") }.getOrDefault(false)
    }

    private fun restoreAlarmVolume() {
        val am = context.getSystemService<AudioManager>() ?: return
        val saved = savedStreamVolume ?: return
        runCatching {
            am.setStreamVolume(AudioManager.STREAM_ALARM, saved, 0)
            am.adjustStreamVolume(AudioManager.STREAM_ALARM,
                if (savedStreamMuted == true) AudioManager.ADJUST_MUTE else AudioManager.ADJUST_UNMUTE, 0)
        }
        savedStreamVolume = null
        savedStreamMuted = null
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

        // Per-file attribution / source line for the bundled set.
        // Keys are asset filenames inside BUNDLED_DIR; values render
        // under the file row in the picker so the listener knows
        // which muezzin or location they're hearing.
        val BUNDLED_CREDITS: Map<String, String> = mapOf(
            "abdullah_baafif_haram.mp3" to "Sheikh Abdullah Ba'afif · Masjid Al Haram",
            "ali_ahmed_mulla_makkah.mp3" to "Sheikh Ali Ahmed Mulla · Mecca",
            "ali_mullah_friday_2014.mp3" to "Sheikh Ali Mullah · 7 March 2014",
            "al_aqsa_jerusalem.mp3" to "Masjid Al Aqsa · Jerusalem",
            "emotional_adhan.mp3" to "\"Most beautiful azan in the world\"",
            "makkah_fajr.mp3" to "Fajr from Makkah",
            "mohammed_amin.mp3" to "Mohammed Amin",
            "most_beautiful_fajr.mp3" to "Generic \"Most Beautiful Fajr Adhan\"",
            "raad_al_kurdi.mp3" to "Raad Muhammad Al Kurdi",
            "soothing_fajr_dawn.mp3" to "Soothing Islamic call to prayer",
        )
    }
}
