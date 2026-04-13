package net.omarss.omono.buildlogic

import com.android.build.api.dsl.ApplicationExtension
import com.android.build.api.dsl.CommonExtension
import com.android.build.api.dsl.LibraryExtension
import org.gradle.api.Plugin
import org.gradle.api.Project
import org.gradle.api.artifacts.VersionCatalogsExtension
import org.gradle.kotlin.dsl.dependencies

// Enables Jetpack Compose. Must be applied AFTER omono.android.application
// or omono.android.library — it hooks into whichever Android extension exists.
class AndroidComposeConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) = with(target) {
        pluginManager.apply("org.jetbrains.kotlin.plugin.compose")

        pluginManager.withPlugin("com.android.application") {
            extensions.configure(ApplicationExtension::class.java) { enableCompose(this) }
        }
        pluginManager.withPlugin("com.android.library") {
            extensions.configure(LibraryExtension::class.java) { enableCompose(this) }
        }

        val libs = extensions.getByType(VersionCatalogsExtension::class.java).named("libs")
        dependencies {
            val bom = libs.findLibrary("androidx-compose-bom").get()
            add("implementation", platform(bom))
            add("androidTestImplementation", platform(bom))

            add("implementation", libs.findLibrary("androidx-compose-ui").get())
            add("implementation", libs.findLibrary("androidx-compose-ui-graphics").get())
            add("implementation", libs.findLibrary("androidx-compose-ui-tooling-preview").get())
            add("implementation", libs.findLibrary("androidx-compose-material3").get())
            add("implementation", libs.findLibrary("androidx-activity-compose").get())
            add("implementation", libs.findLibrary("androidx-lifecycle-runtime-compose").get())

            add("debugImplementation", libs.findLibrary("androidx-compose-ui-tooling").get())
        }
    }

    private fun enableCompose(extension: CommonExtension<*, *, *, *, *, *>) {
        extension.buildFeatures.compose = true
    }
}
