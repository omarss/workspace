package net.omarss.omono.feature.selfupdate

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import okhttp3.OkHttpClient
import okhttp3.Request
import timber.log.Timber
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

// Coordinates the three pieces of the self-update flow — discovery
// (client), download (OkHttp streaming), and handing the APK to the
// system installer (ApkInstaller). Kept purposely thin so the VM can
// wire it straight into compose state without any extra glue.
@Singleton
class SelfUpdateRepository @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val client: SelfUpdateClient,
    private val installer: ApkInstaller,
) {

    // Separate OkHttp instance with no read timeout — APK downloads are
    // multi-megabyte on variable mobile connections; the default 10s
    // read timeout aborts half-transferred files.
    private val downloadHttp: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .build()
    }

    // Returns null when the installed build is already on or past the
    // newest published release. Any network / parse error is logged and
    // returned as null so the UI silently skips the banner.
    suspend fun check(currentVersion: String): UpdateInfo? {
        return runCatching {
            val releases = client.fetchReleases()
            if (releases.isEmpty()) return@runCatching null
            val latest = releases.first()
            if (compareVersions(latest.version, currentVersion) <= 0) return@runCatching null
            val newer = releases.takeWhile {
                compareVersions(it.version, currentVersion) > 0
            }
            UpdateInfo(
                latest = latest,
                cumulativeChangelog = newer.flatMap { release ->
                    release.changelog.map { "${release.version}: $it" }
                },
                apkUrl = client.apkUrl(latest.apkFileName),
            )
        }.getOrElse {
            Timber.w(it, "self-update check failed")
            null
        }
    }

    // Streams the APK into the app's cache dir under updates/. Emits
    // progress as an integer 0..100 so the composable banner can animate
    // a LinearProgressIndicator without any extra transform. On success
    // the terminal emission is DownloadState.Done with the final file.
    fun download(info: UpdateInfo): Flow<DownloadState> = flow {
        emit(DownloadState.InProgress(0))
        val cacheDir = File(context.cacheDir, "updates").apply { mkdirs() }
        // Clean stale APKs so the cache doesn't grow unbounded across
        // multiple releases — we only ever need the file we're about
        // to hand the system installer.
        cacheDir.listFiles()?.forEach { it.delete() }

        val target = File(cacheDir, "omono-${info.latest.version}.apk")
        val request = Request.Builder().url(info.apkUrl).get().build()

        downloadHttp.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IOException("download HTTP ${response.code}")
            }
            val body = response.body ?: throw IOException("empty download body")
            val total = body.contentLength().takeIf { it > 0 } ?: info.latest.sizeBytes
            body.byteStream().use { input ->
                target.outputStream().use { output ->
                    val buffer = ByteArray(64 * 1024)
                    var read: Int
                    var transferred = 0L
                    var lastEmitted = -1
                    while (true) {
                        read = input.read(buffer)
                        if (read == -1) break
                        output.write(buffer, 0, read)
                        transferred += read
                        if (total > 0) {
                            val percent = ((transferred * 100) / total).toInt().coerceIn(0, 99)
                            if (percent != lastEmitted) {
                                lastEmitted = percent
                                emit(DownloadState.InProgress(percent))
                            }
                        }
                    }
                }
            }
        }

        val expected = info.latest.sha256
        if (expected.isNotBlank()) {
            val actual = target.sha256Hex()
            if (!actual.equals(expected, ignoreCase = true)) {
                target.delete()
                throw IOException("checksum mismatch: expected $expected, got $actual")
            }
        }
        emit(DownloadState.InProgress(100))
        emit(DownloadState.Done(target))
    }.flowOn(Dispatchers.IO)

    fun install(file: File) {
        installer.install(file)
    }

    fun canInstallPackages(): Boolean = installer.canInstallPackages()

    fun requestInstallPermission() {
        installer.requestInstallPermission()
    }
}

sealed interface DownloadState {
    data class InProgress(val percent: Int) : DownloadState
    data class Done(val apk: File) : DownloadState
}

private fun File.sha256Hex(): String {
    val digest = MessageDigest.getInstance("SHA-256")
    inputStream().use { input ->
        val buffer = ByteArray(64 * 1024)
        while (true) {
            val read = input.read(buffer)
            if (read == -1) break
            digest.update(buffer, 0, read)
        }
    }
    return digest.digest().joinToString("") { "%02x".format(it) }
}
