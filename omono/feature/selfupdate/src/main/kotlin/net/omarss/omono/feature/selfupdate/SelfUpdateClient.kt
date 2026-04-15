package net.omarss.omono.feature.selfupdate

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import timber.log.Timber
import java.io.IOException
import java.util.concurrent.TimeUnit

// Fetches and parses the apps-host manifest. The base URL lives on the
// host this app was sideloaded from; the only reason to expose it as a
// constructor parameter is so tests can point at a local fixture server.
// Not `@Inject`-annotated on purpose — Hilt treats default arguments as
// a second constructor, which is ambiguous. The Hilt binding lives in
// `SelfUpdateHiltModule` which pins `baseUrl` to the production host.
class SelfUpdateClient constructor(
    private val baseUrl: String = DEFAULT_BASE_URL,
) {

    // Dedicated OkHttp instance with aggressive timeouts — the check
    // runs on every app launch and we never want it to block the UI
    // waiting on a slow DNS resolve.
    private val http: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .build()
    }

    // Returns the full list of releases for the given app id, newest
    // first (matching the publish script's ordering). Throws on network
    // or parse errors — the caller maps those to a silent "no update".
    suspend fun fetchReleases(appId: String = DEFAULT_APP_ID): List<Release> =
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url("$baseUrl/manifest.json")
                .header("Cache-Control", "no-cache")
                .get()
                .build()
            http.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    throw IOException("manifest.json HTTP ${response.code}")
                }
                val body = response.body?.string().orEmpty()
                parseReleases(body, appId)
            }
        }

    // URL of a specific APK file (the manifest stores only the file
    // name so the host can be swapped without touching the manifest).
    fun apkUrl(fileName: String): String = "$baseUrl/$fileName"

    internal fun parseReleases(json: String, appId: String): List<Release> {
        val root = runCatching { JSONObject(json) }.getOrElse {
            Timber.w(it, "manifest.json not valid JSON")
            return emptyList()
        }
        val apps = root.optJSONObject("apps") ?: return emptyList()
        val app = apps.optJSONObject(appId) ?: return emptyList()
        val releases = app.optJSONArray("releases") ?: return emptyList()
        val out = ArrayList<Release>(releases.length())
        for (i in 0 until releases.length()) {
            val obj = releases.optJSONObject(i) ?: continue
            val version = obj.optString("version").takeIf { it.isNotBlank() } ?: continue
            val apk = obj.optString("apk").takeIf { it.isNotBlank() } ?: continue
            val rawChangelog = obj.optJSONArray("changelog")
            val changelog = buildList {
                if (rawChangelog != null) {
                    for (j in 0 until rawChangelog.length()) {
                        val line = rawChangelog.optString(j)
                        if (line.isNotBlank()) add(line)
                    }
                }
            }
            out += Release(
                version = version,
                apkFileName = apk,
                sizeBytes = obj.optLong("size_bytes", -1L),
                sha256 = obj.optString("sha256"),
                changelog = changelog,
                releasedAt = obj.optString("released_at"),
            )
        }
        return out
    }

    companion object {
        const val DEFAULT_BASE_URL: String = "https://apps.omarss.net"
        const val DEFAULT_APP_ID: String = "omono"
    }
}
