package net.omarss.omono.feature.spending

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.database.ContentObserver
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.Telephony
import androidx.core.content.ContextCompat
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant
import java.time.ZoneId
import javax.inject.Inject
import javax.inject.Singleton

// Reads bank SMS out of the system inbox, parses them via SmsParser,
// and exposes today/this-month spending totals. Hot-refreshes via a
// ContentObserver on the SMS URI so the notification stays in sync
// within a second of a new transaction arriving — no polling needed.
//
// The repository only queries within a conservative LOOKBACK window
// so we don't scan years of SMS on every refresh. 40 days covers the
// "spent this month" calculation even at the start of a new month.
@Singleton
class SpendingRepository @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    fun hasReadSmsPermission(): Boolean =
        ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.READ_SMS,
        ) == PackageManager.PERMISSION_GRANTED

    // Emits Unit each time the SMS inbox changes (new message, deleted
    // message, marked read, etc.). Consumers re-read the inbox in
    // response. Single upstream source handles lifecycle + observer
    // cleanup via callbackFlow's awaitClose.
    fun observeInboxChanges(): Flow<Unit> = callbackFlow {
        // Initial emission so the collector gets a value the moment it
        // subscribes; subsequent emissions come from the observer.
        trySend(Unit)

        val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean, uri: Uri?) {
                trySend(Unit)
            }
        }
        context.contentResolver.registerContentObserver(
            Telephony.Sms.CONTENT_URI,
            true,
            observer,
        )
        awaitClose {
            context.contentResolver.unregisterContentObserver(observer)
        }
    }

    suspend fun currentTotals(
        now: Instant = Instant.now(),
        zone: ZoneId = ZoneId.systemDefault(),
    ): SpendingTotals {
        if (!hasReadSmsPermission()) return SpendingTotals.Empty
        val transactions = loadRecentTransactions(now.minusMillis(LOOKBACK_MILLIS).toEpochMilli())
        return computeTotals(transactions, now, zone)
    }

    // Public accessor for the raw parsed transactions inside the
    // rolling window — used by the finance dashboard which needs the
    // per-transaction list for recent activity, top merchants, etc.
    suspend fun recentTransactions(
        sinceMillis: Long = System.currentTimeMillis() - LOOKBACK_MILLIS,
    ): List<Transaction> {
        if (!hasReadSmsPermission()) return emptyList()
        return loadRecentTransactions(sinceMillis)
    }

    @SuppressLint("Recycle")
    private suspend fun loadRecentTransactions(sinceMillis: Long): List<Transaction> =
        withContext(Dispatchers.IO) {
            val projection = arrayOf(
                Telephony.Sms.ADDRESS,
                Telephony.Sms.BODY,
                Telephony.Sms.DATE,
            )
            val selection = "${Telephony.Sms.DATE} >= ?"
            val args = arrayOf(sinceMillis.toString())

            val result = mutableListOf<Transaction>()
            runCatching {
                context.contentResolver.query(
                    Telephony.Sms.Inbox.CONTENT_URI,
                    projection,
                    selection,
                    args,
                    "${Telephony.Sms.DATE} DESC",
                )
            }.onFailure {
                Timber.w(it, "SMS inbox query failed")
            }.getOrNull()?.use { cursor ->
                val addressIdx = cursor.getColumnIndexOrThrow(Telephony.Sms.ADDRESS)
                val bodyIdx = cursor.getColumnIndexOrThrow(Telephony.Sms.BODY)
                val dateIdx = cursor.getColumnIndexOrThrow(Telephony.Sms.DATE)
                while (cursor.moveToNext()) {
                    val address = cursor.getString(addressIdx)
                    if (!SmsParser.isKnownSender(address)) continue
                    val body = cursor.getString(bodyIdx) ?: continue
                    val date = cursor.getLong(dateIdx)
                    val parsed = SmsParser.parse(address, body) ?: continue
                    result += Transaction(
                        amountSar = parsed.amountSar,
                        timestampMillis = date,
                        bank = parsed.bank,
                        kind = parsed.kind,
                        merchant = parsed.merchant,
                    )
                }
            }
            result
        }

    private companion object {
        // ~40 days of history is enough for a "this month" calculation
        // even if the user opens the app on the 1st.
        const val LOOKBACK_MILLIS: Long = 40L * 24 * 60 * 60 * 1000
    }
}
