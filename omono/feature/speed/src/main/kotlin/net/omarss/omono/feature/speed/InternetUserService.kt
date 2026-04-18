package net.omarss.omono.feature.speed

import timber.log.Timber
import kotlin.system.exitProcess

// User service implementation hosted by Shizuku. Runs in a separate
// process launched via bindUserService — that process inherits ADB's
// permission set, which is what lets us invoke `svc wifi disable`
// etc. without root.
//
// Do NOT add Hilt / Context / coroutine deps here: the process is
// bare, spawned by Shizuku, and cannot see the app's Hilt graph. It
// only has whatever is reachable from the classpath of the AAR +
// what we manually pass over the binder.
class InternetUserService : IInternetService.Stub() {

    override fun runSvc(subsystem: String, action: String): Int {
        return try {
            val process = Runtime.getRuntime().exec(arrayOf("svc", subsystem, action))
            val exit = process.waitFor()
            if (exit != 0) {
                Timber.w("InternetUserService: svc %s %s exit=%d", subsystem, action, exit)
            }
            exit
        } catch (e: Exception) {
            Timber.w(e, "InternetUserService: svc %s %s threw", subsystem, action)
            -1
        }
    }

    override fun destroy() {
        // Shizuku calls this on unbind. Terminate the user-service
        // process so it doesn't linger in the system.
        exitProcess(0)
    }
}
