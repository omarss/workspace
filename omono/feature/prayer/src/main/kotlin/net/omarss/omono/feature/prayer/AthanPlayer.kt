package net.omarss.omono.feature.prayer

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.net.Uri
import android.provider.OpenableColumns
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

// Plays the athan (call to prayer) when Fajr arrives. Source files are
// read from the app's external files directory
// (`<sdcard>/Android/data/net.omarss.omono/files/athans/`), which is
// reachable via USB / the device's file manager — no runtime permission
// needed because app-specific external storage is public to the app.
//
// At Fajr time the player picks a random file from that directory. If
// the directory is empty (e.g. fresh install), it falls back to the
// device's default alarm sound so the user still gets an audible cue.
// Users drop their 10 preferred recordings in the directory via USB.
//
// The player is one-shot and fire-and-forget — the caller doesn't wait
// on the MediaPlayer to finish. A second trigger while the first is
// still playing interrupts with the new file, which is the right
// behaviour for rare double-fires.
@Singleton
class AthanPlayer @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    @Volatile private var current: MediaPlayer? = null

    // Returns the directory where the user should drop athan audio
    // files. Created on demand. Exposed so the Prayer screen can
    // show it to the user and link the file-manager to open it.
    fun athansDirectory(): File {
        val dir = File(context.getExternalFilesDir(null), DIRECTORY_NAME)
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    fun availableAthans(): List<File> {
        val dir = athansDirectory()
        return dir.listFiles { f -> f.isFile && f.isReadableAudio() }
            ?.toList().orEmpty()
    }

    // Fire-and-forget athan playback. `selection` decides *which*
    // file from the pool plays:
    //   * Random — one of the available files, uniformly at random.
    //   * Specific(name) — the named file, falling back to Random
    //     when the pinned file has been deleted since the setting
    //     was written.
    // When the pool is empty the device's default alarm sound fires
    // so the user never silently misses a Fajr. Returns false only
    // if the platform has no default alarm sound either (extremely
    // unlikely on a real Android device).
    fun play(selection: AthanSelection = AthanSelection.Random): Boolean {
        stop()
        val pool = availableAthans()
        val chosen: File? = when {
            pool.isEmpty() -> null
            selection is AthanSelection.Specific ->
                pool.firstOrNull { it.name == selection.fileName } ?: pool.random()
            else -> pool.random()
        }
        val player = if (chosen != null) {
            Timber.i("AthanPlayer: playing %s", chosen.name)
            startFromFile(chosen) ?: startFromDefault()
        } else {
            Timber.i("AthanPlayer: no user files in %s, using default alarm", athansDirectory())
            startFromDefault()
        }
        current = player
        return player != null
    }

    // Back-compat shim — `playRandom()` was the original name. Kept
    // so the alarm receiver's existing call site doesn't churn.
    @Deprecated(
        "Use play(AthanSelection) directly; kept for call-site compatibility.",
        ReplaceWith("play(AthanSelection.Random)"),
    )
    fun playRandom(): Boolean = play(AthanSelection.Random)

    // Copies the content behind a SAF uri (ACTION_OPEN_DOCUMENT
    // result) into the athans directory. The filename comes from
    // the original document's display name when available, else a
    // timestamp-based fallback. Returns the copied File on success.
    //
    // The copy is necessary because SAF uris can be revoked at any
    // time (user removes permission, app process dies, etc.); by
    // the time Fajr alarm fires the permission may be gone. Keeping
    // a local copy under the app's own files dir sidesteps that.
    fun importFromUri(uri: Uri): File? {
        val name = queryDisplayName(uri)
            ?: "athan-${System.currentTimeMillis()}.mp3"
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

    private fun queryDisplayName(uri: Uri): String? {
        return runCatching {
            context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { cursor ->
                    if (cursor.moveToFirst()) cursor.getString(0) else null
                }
        }.getOrNull()
    }

    private fun sanitizeFileName(name: String): String {
        // Keep alphanumerics, dashes, underscores, dots, spaces — strip
        // everything else so a weird SAF display name doesn't produce
        // a path that breaks on other filesystems / shell tools.
        val cleaned = name.replace(Regex("[^A-Za-z0-9._\\- ]+"), "_").trim()
        return cleaned.ifEmpty { "athan.mp3" }
    }

    fun stop() {
        current?.let { mp ->
            runCatching {
                if (mp.isPlaying) mp.stop()
                mp.release()
            }
        }
        current = null
    }

    private fun startFromFile(file: File): MediaPlayer? {
        return runCatching {
            MediaPlayer().apply {
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build(),
                )
                setDataSource(file.absolutePath)
                setOnCompletionListener { runCatching { release() } }
                setOnErrorListener { _, _, _ -> runCatching { release() }; true }
                prepare()
                start()
            }
        }.onFailure { Timber.w(it, "AthanPlayer: failed to play %s", file.name) }
            .getOrNull()
    }

    private fun startFromDefault(): MediaPlayer? {
        val uri: Uri = RingtoneManager.getActualDefaultRingtoneUri(
            context,
            RingtoneManager.TYPE_ALARM,
        ) ?: RingtoneManager.getActualDefaultRingtoneUri(
            context,
            RingtoneManager.TYPE_NOTIFICATION,
        ) ?: return null
        return runCatching {
            MediaPlayer().apply {
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build(),
                )
                setDataSource(context, uri)
                setOnCompletionListener { runCatching { release() } }
                setOnErrorListener { _, _, _ -> runCatching { release() }; true }
                prepare()
                start()
            }
        }.onFailure { Timber.w(it, "AthanPlayer: default sound fallback failed") }
            .getOrNull()
    }

    private fun File.isReadableAudio(): Boolean {
        val ext = extension.lowercase()
        return ext in SUPPORTED_EXTS
    }

    private companion object {
        const val DIRECTORY_NAME = "athans"
        val SUPPORTED_EXTS = setOf("mp3", "ogg", "m4a", "aac", "wav", "flac", "opus")
    }
}
