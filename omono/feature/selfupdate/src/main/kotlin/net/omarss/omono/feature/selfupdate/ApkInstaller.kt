package net.omarss.omono.feature.selfupdate

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.provider.Settings
import androidx.core.net.toUri
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

// Hands a downloaded APK to the platform's PackageInstaller. The Session
// API is the modern replacement for ACTION_VIEW + application/vnd.android
// intents — it supports streaming writes, atomic commit, and doesn't
// require a FileProvider URI grant dance.
//
// The user is still prompted to confirm the install (Android will not
// let a sideloaded app silently replace itself — that's a Play-only
// privilege), but after confirming, the next launch comes up on the
// freshly installed build.
@Singleton
class ApkInstaller @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    // minSdk is 26 (Oreo), so this toggle always applies — the user
    // must explicitly grant "Install unknown apps" for omono before we
    // even attempt a download.
    fun canInstallPackages(): Boolean =
        context.packageManager.canRequestPackageInstalls()

    fun requestInstallPermission() {
        val intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
            .setData("package:${context.packageName}".toUri())
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching { context.startActivity(intent) }
            .onFailure { Timber.w(it, "unable to launch unknown sources settings") }
    }

    fun install(apk: File) {
        if (!apk.exists() || apk.length() == 0L) {
            Timber.w("install requested with missing/empty apk at $apk")
            return
        }
        val packageInstaller = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(
            PackageInstaller.SessionParams.MODE_FULL_INSTALL,
        ).apply {
            setAppPackageName(context.packageName)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED)
            }
        }

        val sessionId = runCatching { packageInstaller.createSession(params) }.getOrElse {
            Timber.e(it, "failed to create install session")
            return
        }

        runCatching {
            packageInstaller.openSession(sessionId).use { session ->
                apk.inputStream().use { input ->
                    session.openWrite("omono.apk", 0, apk.length()).use { output ->
                        input.copyTo(output)
                        session.fsync(output)
                    }
                }
                // Explicit-component intent to the manifest-declared
                // receiver. A dynamically-registered receiver does
                // NOT reliably receive these callbacks on Android
                // 14+ — the install dialog simply never appears —
                // so this path only works with the static receiver
                // in feature/selfupdate's AndroidManifest.xml.
                val intent = Intent(context, InstallResultReceiver::class.java).apply {
                    action = INSTALL_ACTION
                    setPackage(context.packageName)
                }
                val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
                val pending = PendingIntent.getBroadcast(context, sessionId, intent, flags)
                session.commit(pending.intentSender)
            }
        }.onFailure {
            Timber.e(it, "install session commit failed")
            runCatching { packageInstaller.abandonSession(sessionId) }
        }
    }

    internal companion object {
        const val INSTALL_ACTION: String = "net.omarss.omono.feature.selfupdate.INSTALL_RESULT"
    }
}

// Dynamically registered receiver that escalates a pending install into
// the system confirmation activity. Declared here (not in the manifest)
// because it only needs to live for the duration of a commit.
internal class InstallResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(
            PackageInstaller.EXTRA_STATUS,
            PackageInstaller.STATUS_FAILURE,
        )
        when (status) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirm = intent.parcelable<Intent>(Intent.EXTRA_INTENT)
                if (confirm != null) {
                    confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    runCatching { context.startActivity(confirm) }
                        .onFailure { Timber.w(it, "failed to launch installer confirmation") }
                }
            }
            PackageInstaller.STATUS_SUCCESS -> Timber.i("self-update install succeeded")
            else -> {
                val message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)
                Timber.w("self-update install failed status=$status message=$message")
            }
        }
    }
}

private inline fun <reified T> Intent.parcelable(key: String): T? =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        getParcelableExtra(key, T::class.java)
    } else {
        @Suppress("DEPRECATION")
        getParcelableExtra(key)
    }
