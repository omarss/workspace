package net.omarss.omono.feature.prayer

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.net.Uri
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

    // Fire-and-forget athan playback. Returns true if playback
    // started successfully (bundled file found OR default alarm sound
    // available). `false` means the device has no athan and no
    // default — extremely unlikely on a real Android.
    fun playRandom(): Boolean {
        stop()
        val pool = availableAthans()
        val player = if (pool.isNotEmpty()) {
            val chosen = pool.random()
            Timber.i("AthanPlayer: playing user file %s", chosen.name)
            startFromFile(chosen) ?: startFromDefault()
        } else {
            Timber.i("AthanPlayer: no user files in %s, using default alarm sound", athansDirectory())
            startFromDefault()
        }
        current = player
        return player != null
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
