package net.omarss.omono.buildlogic

import org.gradle.api.Project
import org.gradle.jvm.toolchain.JavaLanguageVersion
import org.gradle.kotlin.dsl.getByType
import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import org.jetbrains.kotlin.gradle.dsl.KotlinProjectExtension
import org.jetbrains.kotlin.gradle.tasks.KotlinJvmCompile

// Kotlin-only configuration. Android DSL wiring moved to the concrete
// extensions in each plugin because AGP 9 dropped the shared
// CommonExtension members (defaultConfig, compileOptions, etc.).
internal fun Project.configureKotlin() {
    extensions.getByType<KotlinProjectExtension>().apply {
        jvmToolchain { languageVersion.set(JavaLanguageVersion.of(AndroidConfig.JVM_TARGET.toInt())) }
    }

    tasks.withType(KotlinJvmCompile::class.java).configureEach {
        compilerOptions {
            jvmTarget.set(JvmTarget.fromTarget(AndroidConfig.JVM_TARGET))
        }
    }
}
