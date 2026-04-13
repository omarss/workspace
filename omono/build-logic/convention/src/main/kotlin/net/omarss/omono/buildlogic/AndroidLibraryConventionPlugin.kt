package net.omarss.omono.buildlogic

import com.android.build.api.dsl.LibraryExtension
import org.gradle.api.Plugin
import org.gradle.api.Project

class AndroidLibraryConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) = with(target) {
        pluginManager.apply("com.android.library")
        pluginManager.apply("org.jetbrains.kotlin.android")

        // AGP 9: library modules no longer carry targetSdk — it's inherited
        // from the consuming application.
        extensions.configure(LibraryExtension::class.java) {
            compileSdk = AndroidConfig.COMPILE_SDK
            defaultConfig {
                minSdk = AndroidConfig.MIN_SDK
            }
            compileOptions {
                sourceCompatibility = AndroidConfig.JAVA_VERSION
                targetCompatibility = AndroidConfig.JAVA_VERSION
            }
        }

        configureKotlin()
    }
}
