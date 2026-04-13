package net.omarss.omono.buildlogic

import org.gradle.api.Plugin
import org.gradle.api.Project
import org.gradle.api.artifacts.VersionCatalogsExtension
import org.gradle.kotlin.dsl.dependencies

// Umbrella plugin for feature modules: Android library + Compose + Hilt +
// the common/designsystem core deps every feature needs.
class AndroidFeatureConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) = with(target) {
        pluginManager.apply("omono.android.library")
        pluginManager.apply("omono.android.compose")
        pluginManager.apply("omono.android.hilt")

        val libs = extensions.getByType(VersionCatalogsExtension::class.java).named("libs")

        dependencies {
            add("implementation", project(":core:common"))
            add("implementation", project(":core:designsystem"))
            add("implementation", project(":core:service"))
            add("implementation", libs.findLibrary("androidx-lifecycle-runtime-ktx").get())
            add("implementation", libs.findLibrary("androidx-lifecycle-viewmodel-compose").get())
            add("implementation", libs.findLibrary("hilt-navigation-compose").get())
            add("implementation", libs.findLibrary("kotlinx-coroutines-android").get())
        }
    }
}
