plugins {
    alias(libs.plugins.omono.android.library)
    alias(libs.plugins.omono.android.hilt)
}

android {
    namespace = "net.omarss.omono.core.notification"

    testOptions {
        unitTests {
            isIncludeAndroidResources = true
        }
    }
}

dependencies {
    implementation(projects.core.common)
    implementation(libs.androidx.core.ktx)

    testImplementation(libs.junit)
    testImplementation(libs.kotest.assertions.core)
    testImplementation(libs.robolectric)
    testImplementation(libs.androidx.test.core.ktx)
}
