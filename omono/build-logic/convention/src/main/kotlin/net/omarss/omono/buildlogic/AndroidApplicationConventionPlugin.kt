package net.omarss.omono.buildlogic

import com.android.build.api.dsl.ApplicationExtension
import org.gradle.api.Plugin
import org.gradle.api.Project

class AndroidApplicationConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) = with(target) {
        pluginManager.apply("com.android.application")
        pluginManager.apply("org.jetbrains.kotlin.android")

        extensions.configure(ApplicationExtension::class.java) {
            compileSdk = AndroidConfig.COMPILE_SDK
            defaultConfig {
                minSdk = AndroidConfig.MIN_SDK
                targetSdk = AndroidConfig.TARGET_SDK
            }
            compileOptions {
                sourceCompatibility = AndroidConfig.JAVA_VERSION
                targetCompatibility = AndroidConfig.JAVA_VERSION
            }
        }

        configureKotlin()
    }
}
