package net.omarss.omono.feature.spending

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.provider.Telephony
import androidx.core.content.ContextCompat
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

// Dumps every bank-related SMS from the device inbox into a single
// plaintext file so the user can ship it off for parser improvements.
// Keeps the format dead-simple so the receiver (me, reading the
// output) can grep / eyeball patterns without needing a tool.
//
// Each message is rendered as:
//
//     --- 2026-04-15 07:34:12 | AlRajhiBank ---
//     PoS
//     By:8025;mada-mada Pay
//     Amount:SAR 72.05
//     ...
//
// …separated by a blank line. The file lands in the app's cache dir
// so it's cleaned up on reinstall and never leaves the device until
// the user explicitly shares it via ACTION_SEND.
@Singleton
class SmsExporter @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    data class ExportResult(val file: File, val count: Int)

    fun hasReadSmsPermission(): Boolean =
        ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.READ_SMS,
        ) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("Recycle")
    suspend fun export(): ExportResult = withContext(Dispatchers.IO) {
        if (!hasReadSmsPermission()) {
            throw SecurityException("READ_SMS permission not granted")
        }

        val outputDir = File(context.cacheDir, "exports").apply { mkdirs() }
        val file = File(outputDir, "omono-bank-sms.txt")

        val projection = arrayOf(
            Telephony.Sms.ADDRESS,
            Telephony.Sms.BODY,
            Telephony.Sms.DATE,
        )
        // 90 days of history — enough to sample rare transaction types
        // (one-off billers, refunds, declines) without dumping the
        // whole lifetime of the phone.
        val cutoff = System.currentTimeMillis() - LOOKBACK_MS
        val selection = "${Telephony.Sms.DATE} >= ?"
        val args = arrayOf(cutoff.toString())

        val entries = mutableListOf<String>()

        context.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            projection,
            selection,
            args,
            "${Telephony.Sms.DATE} DESC",
        )?.use { cursor ->
            val addrIdx = cursor.getColumnIndexOrThrow(Telephony.Sms.ADDRESS)
            val bodyIdx = cursor.getColumnIndexOrThrow(Telephony.Sms.BODY)
            val dateIdx = cursor.getColumnIndexOrThrow(Telephony.Sms.DATE)
            val dateFmt = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
            while (cursor.moveToNext()) {
                val address = cursor.getString(addrIdx) ?: continue
                if (!SmsParser.isKnownSender(address)) continue
                val body = cursor.getString(bodyIdx) ?: continue
                val date = cursor.getLong(dateIdx)
                entries += "--- ${dateFmt.format(Date(date))} | $address ---\n$body"
            }
        }

        val header = buildString {
            appendLine("# omono bank SMS export")
            appendLine("# Generated: ${SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())}")
            appendLine("# Window: last ${LOOKBACK_MS / (24 * 60 * 60 * 1000)} days")
            appendLine("# Count: ${entries.size}")
            appendLine()
        }
        file.writeText(header + entries.joinToString("\n\n"))
        ExportResult(file, entries.size)
    }

    private companion object {
        const val LOOKBACK_MS: Long = 90L * 24 * 60 * 60 * 1000
    }
}
