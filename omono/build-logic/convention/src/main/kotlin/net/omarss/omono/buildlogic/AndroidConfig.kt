package net.omarss.omono.buildlogic

import org.gradle.api.JavaVersion

// Single source of truth for Android SDK + JVM target across modules.
internal object AndroidConfig {
    const val COMPILE_SDK: Int = 36
    const val TARGET_SDK: Int = 36
    const val MIN_SDK: Int = 26

    val JAVA_VERSION: JavaVersion = JavaVersion.VERSION_17
    const val JVM_TARGET: String = "17"
}
