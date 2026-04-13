package net.omarss.omono.core.service

import androidx.lifecycle.LifecycleService

// The single foreground service that hosts every enabled OmonoFeature.
//
// Scaffold: declares the class so manifests and DI can wire against it.
// Real implementation (collect feature flows, build notifications, handle
// start/stop commands) lands in the next step of the plan.
class FeatureHostService : LifecycleService()
