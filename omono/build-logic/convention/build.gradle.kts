plugins {
    `kotlin-dsl`
}

group = "net.omarss.omono.buildlogic"

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(17)
    }
}

dependencies {
    compileOnly(libs.android.gradle.plugin)
    compileOnly(libs.kotlin.gradle.plugin)
    compileOnly(libs.ksp.gradle.plugin)
    compileOnly(libs.hilt.gradle.plugin)
}

gradlePlugin {
    plugins {
        register("androidApplication") {
            id = "omono.android.application"
            implementationClass = "net.omarss.omono.buildlogic.AndroidApplicationConventionPlugin"
        }
        register("androidLibrary") {
            id = "omono.android.library"
            implementationClass = "net.omarss.omono.buildlogic.AndroidLibraryConventionPlugin"
        }
        register("androidCompose") {
            id = "omono.android.compose"
            implementationClass = "net.omarss.omono.buildlogic.AndroidComposeConventionPlugin"
        }
        register("androidHilt") {
            id = "omono.android.hilt"
            implementationClass = "net.omarss.omono.buildlogic.AndroidHiltConventionPlugin"
        }
        register("androidFeature") {
            id = "omono.android.feature"
            implementationClass = "net.omarss.omono.buildlogic.AndroidFeatureConventionPlugin"
        }
    }
}
