plugins {
    alias(libs.plugins.omono.android.feature)
}

android {
    namespace = "net.omarss.omono.feature.prayer"

    defaultConfig {
        // adhan2 ships Kotlin Multiplatform artefacts — this flag
        // lets Gradle pick the JVM variant for our Android module.
    }

    testOptions {
        unitTests {
            isIncludeAndroidResources = true
        }
    }
}

dependencies {
    implementation(projects.core.common)
    implementation(projects.core.notification)
    implementation(libs.adhan)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.timber)
    implementation(libs.androidx.datastore.preferences)
    implementation(projects.core.data)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.kotest.assertions.core)
}
