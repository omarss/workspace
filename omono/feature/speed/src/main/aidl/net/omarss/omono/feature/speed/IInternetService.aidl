// AIDL for the Shizuku-hosted user service that wraps `svc` shell
// invocations. The user service runs in a process spawned by Shizuku
// with ADB-level permissions, which is what lets a plain APK toggle
// Wi-Fi and mobile data on modern Android.
//
// Transaction IDs: destroy() is pinned to Shizuku's reserved 16777114
// (its standard "tear down user service" slot). All other methods get
// automatic IDs.
package net.omarss.omono.feature.speed;

interface IInternetService {
    int runSvc(String subsystem, String action) = 1;

    // Shizuku sends this when the app unbinds. We call System.exit(0)
    // to free the user-service process immediately. The high
    // transaction ID matches Shizuku's reserved "tear down user
    // service" slot.
    void destroy() = 16777114;
}
