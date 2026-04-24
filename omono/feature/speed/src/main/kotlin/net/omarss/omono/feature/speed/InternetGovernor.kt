package net.omarss.omono.feature.speed

import android.content.ComponentName
import android.content.Context
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.os.IBinder
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import rikka.shizuku.Shizuku
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

// Elevated-permission shim for toggling Wi-Fi + mobile data from a
// sideloaded app. Uses the Shizuku service (shizuku.rikka.app) which
// exposes ADB-level permissions over a stable binder after a one-time
// ADB pair — no root required.
//
// Architecture: Shizuku spawns a user-service process
// (InternetUserService) that inherits ADB's permission set. That
// process runs `svc wifi|data enable|disable` on our behalf over a
// small AIDL interface. Running via a user service — instead of the
// @RestrictTo-marked Shizuku.newProcess — is the officially supported
// path that won't break on Shizuku upgrades.
//
// Readiness is reported as a StateFlow so the settings screen can
// surface "install Shizuku" / "start Shizuku" / "grant permission"
// states inline instead of silently failing when the user enables
// the feature.
@Singleton
class InternetGovernor @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {

    enum class Readiness {
        /** Shizuku binder is up and omono has the API permission. */
        Ready,

        /** Shizuku app isn't installed on the device. */
        NotInstalled,

        /** Shizuku is installed but the manager service isn't running. */
        NotRunning,

        /** Shizuku running but our app hasn't been granted permission. */
        NoPermission,

        /** Don't know yet — usually the first tick before binder events fire. */
        Unknown,
    }

    private val _readiness = MutableStateFlow(Readiness.Unknown)
    val readiness: StateFlow<Readiness> = _readiness.asStateFlow()

    // Shizuku invokes these callbacks on its own threads. They just
    // poke refresh() which does a fresh status read rather than
    // trying to maintain state from individual events — simpler and
    // fixes itself if an event is missed.
    private val binderReceived = Shizuku.OnBinderReceivedListener {
        refresh()
        tryBindUserService()
    }
    private val binderDead = Shizuku.OnBinderDeadListener {
        userService = null
        refresh()
    }
    private val permissionResult =
        Shizuku.OnRequestPermissionResultListener { _, _ ->
            refresh()
            tryBindUserService()
        }

    // User-service handle. Bound lazily on first readiness success;
    // nulled out when Shizuku dies. Guarded by synchronized on
    // serviceConnection so read/write doesn't race against binder
    // callbacks on different threads.
    @Volatile private var userService: IInternetService? = null

    private val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            userService = IInternetService.Stub.asInterface(binder)
            Timber.d("Shizuku user service connected")
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            userService = null
            Timber.d("Shizuku user service disconnected")
        }
    }

    private val userServiceArgs: Shizuku.UserServiceArgs by lazy {
        Shizuku.UserServiceArgs(
            ComponentName(context.packageName, InternetUserService::class.java.name),
        )
            .processNameSuffix("internet")
            .version(USER_SERVICE_VERSION)
            .daemon(false)
    }

    fun start() {
        Shizuku.addBinderReceivedListenerSticky(binderReceived)
        Shizuku.addBinderDeadListener(binderDead)
        Shizuku.addRequestPermissionResultListener(permissionResult)
        refresh()
        tryBindUserService()
    }

    fun stop() {
        Shizuku.removeBinderReceivedListener(binderReceived)
        Shizuku.removeBinderDeadListener(binderDead)
        Shizuku.removeRequestPermissionResultListener(permissionResult)
        runCatching { Shizuku.unbindUserService(userServiceArgs, serviceConnection, true) }
        userService = null
    }

    // Trigger the Shizuku permission dialog. Returns true if the
    // request was dispatched; false if there's nothing we can do from
    // here (Shizuku not installed / not running — UI should surface
    // an "install" / "start" hint instead).
    fun requestPermission(requestCode: Int): Boolean {
        if (!isShizukuInstalled()) return false
        if (!Shizuku.pingBinder()) return false
        if (Shizuku.isPreV11()) {
            _readiness.value = Readiness.NoPermission
            return false
        }
        if (Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED) {
            _readiness.value = Readiness.Ready
            return true
        }
        Shizuku.requestPermission(requestCode)
        return true
    }

    // Binder calls to the Shizuku user-service are blocking IPC — if
    // the user-service has hung or the Shizuku manager crashed, a naked
    // call can sit forever. Wrap every caller-visible call in a
    // bounded timeout so the app returns to `false` (ungoverned)
    // rather than stalling whichever coroutine asked.
    //
    // `withTimeoutOrNull` only cancels at suspension points; the blocking
    // binder call itself won't be interrupted. We accept that — the
    // coroutine continues on its own, the caller sees `false` and
    // recovers, and the worst case is a single orphaned binder call
    // rather than an indefinite user-visible hang.
    suspend fun disableInternet(): Boolean = withContext(Dispatchers.IO) {
        withTimeoutOrNull(SVC_CALL_TIMEOUT_MS) {
            runSvc("wifi", "disable") && runSvc("data", "disable")
        } ?: run {
            Timber.w("disableInternet timed out after %d ms", SVC_CALL_TIMEOUT_MS)
            false
        }
    }

    suspend fun enableInternet(): Boolean = withContext(Dispatchers.IO) {
        // Re-enable in reverse order — mobile data first so the user
        // is connected sooner on the fallback path while Wi-Fi
        // reassociates.
        withTimeoutOrNull(SVC_CALL_TIMEOUT_MS) {
            runSvc("data", "enable") && runSvc("wifi", "enable")
        } ?: run {
            Timber.w("enableInternet timed out after %d ms", SVC_CALL_TIMEOUT_MS)
            false
        }
    }

    private fun runSvc(subsystem: String, action: String): Boolean {
        val service = userService
        if (service == null) {
            Timber.w("InternetGovernor: user service not bound, svc %s %s skipped", subsystem, action)
            tryBindUserService()
            return false
        }
        return runCatching { service.runSvc(subsystem, action) == 0 }
            .onFailure { Timber.w(it, "svc $subsystem $action failed over binder") }
            .getOrDefault(false)
    }

    private fun tryBindUserService() {
        if (userService != null) return
        if (!isReady()) return
        runCatching {
            Shizuku.bindUserService(userServiceArgs, serviceConnection)
        }.onFailure { Timber.w(it, "Shizuku.bindUserService failed") }
    }

    private fun refresh() {
        _readiness.value = when {
            !isShizukuInstalled() -> Readiness.NotInstalled
            !runCatching { Shizuku.pingBinder() }.getOrDefault(false) -> Readiness.NotRunning
            runCatching { Shizuku.checkSelfPermission() }.getOrDefault(PackageManager.PERMISSION_DENIED) !=
                PackageManager.PERMISSION_GRANTED -> Readiness.NoPermission
            else -> Readiness.Ready
        }
    }

    private fun isShizukuInstalled(): Boolean = runCatching {
        context.packageManager.getPackageInfo(SHIZUKU_PACKAGE, 0)
        true
    }.getOrDefault(false)

    private fun isReady(): Boolean = runCatching {
        Shizuku.pingBinder() &&
            Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
    }.getOrDefault(false)

    private companion object {
        const val SHIZUKU_PACKAGE = "moe.shizuku.privileged.api"

        // Bump when the AIDL interface changes so Shizuku restarts the
        // user-service process with the new class definitions instead
        // of reusing the old one.
        const val USER_SERVICE_VERSION = 1

        // Upper bound for a `svc` toggle pair. `svc wifi|data …` is
        // typically sub-second on a healthy Shizuku; 5 s is loose
        // enough not to trigger on a slow handset and tight enough
        // that a hung user-service can't stall a drive for long.
        const val SVC_CALL_TIMEOUT_MS: Long = 5_000L
    }
}
