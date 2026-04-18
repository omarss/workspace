package net.omarss.omono.diagnostics

import android.content.Context
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import java.io.File
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

// Timber tree that persists log lines to a rotated file under
// filesDir/logs. Produces a "share diagnostics" payload the user can
// email / send via ACTION_SEND for post-hoc debugging — invaluable
// on a personal sideload where the phone is the only place a
// strange drive ever shows up.
//
// Rotation: one active file (app.log) and one rolled-over backup
// (app.1.log). When the active file exceeds MAX_SIZE the rolled
// backup is deleted and the active file takes its place, leaving an
// empty active file for new writes. Cap: ~1 MB total on disk.
@Singleton
class DiagnosticsLogger @Inject constructor(
    @param:ApplicationContext private val context: Context,
) : Timber.Tree() {

    private val logDir: File by lazy {
        File(context.filesDir, "logs").apply { runCatching { mkdirs() } }
    }
    private val current: File get() = File(logDir, "app.log")
    private val rolled: File get() = File(logDir, "app.1.log")
    private val lock = Any()
    private val lineFormat = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.ROOT)

    override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
        if (priority < Log.INFO) return // keep the file lean — debug/verbose noise stays in logcat
        val line = buildLine(priority, tag, message, t)
        synchronized(lock) {
            runCatching {
                if (current.length() > MAX_SIZE) {
                    rolled.delete()
                    current.renameTo(rolled)
                }
                current.appendText(line)
            }.onFailure {
                // Deliberately don't log through Timber here — would
                // recurse straight back into this tree.
                Log.w(TIMBER_TAG, "Failed to write diagnostics line", it)
            }
        }
    }

    // Returns a single file containing the concatenated rolled-over +
    // current log. Written under cacheDir/exports/ so the existing
    // FileProvider path (shared with the SMS export) can serve it
    // without exposing the rotating log handles.
    fun buildSharePayload(): File {
        val exportsDir = File(context.cacheDir, "exports").apply { runCatching { mkdirs() } }
        val out = File(exportsDir, "omono-diagnostics.txt")
        synchronized(lock) {
            runCatching {
                out.writer().use { w ->
                    if (rolled.exists()) w.write(rolled.readText())
                    if (current.exists()) w.write(current.readText())
                }
            }.onFailure { throw IOException("Failed to build diagnostics payload", it) }
        }
        return out
    }

    private fun buildLine(
        priority: Int,
        tag: String?,
        message: String,
        t: Throwable?,
    ): String {
        val ts = lineFormat.format(Date())
        val level = when (priority) {
            Log.VERBOSE -> "V"
            Log.DEBUG -> "D"
            Log.INFO -> "I"
            Log.WARN -> "W"
            Log.ERROR -> "E"
            Log.ASSERT -> "A"
            else -> "?"
        }
        val tagPart = tag ?: "-"
        val throwable = t?.let { "\n${Log.getStackTraceString(it)}" }.orEmpty()
        return "$ts $level/$tagPart: $message$throwable\n"
    }

    private companion object {
        const val MAX_SIZE: Long = 512L * 1024 // 512 KB active → ~1 MB total with rolled
        const val TIMBER_TAG = "DiagnosticsLogger"
    }
}
