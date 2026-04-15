plugins {
    alias(libs.plugins.omono.android.feature)
}

android {
    namespace = "net.omarss.omono.feature.selfupdate"

    testOptions {
        unitTests {
            isIncludeAndroidResources = true
        }
    }
}

dependencies {
    implementation(projects.core.common)
    implementation(projects.core.notification)
    implementation(libs.okhttp)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.timber)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.kotest.assertions.core)
    testImplementation(libs.robolectric)
    testImplementation(libs.androidx.test.core.ktx)
}
