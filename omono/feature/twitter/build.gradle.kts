plugins {
    alias(libs.plugins.omono.android.feature)
}

android {
    namespace = "net.omarss.omono.feature.twitter"

    testOptions {
        unitTests {
            isIncludeAndroidResources = true
        }
    }
}

dependencies {
    implementation(projects.core.common)
    implementation(libs.okhttp)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.timber)
    // Coil for avatar rendering on the Feed tab.
    implementation(libs.coil.compose)
    implementation(libs.coil.network.okhttp)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.kotest.assertions.core)
    // org.json is an Android-framework stub on the JVM test classpath
    // (every call throws); Robolectric ships a real impl so the
    // parser tests can exercise JSONObject directly.
    testImplementation(libs.robolectric)
    testImplementation(libs.androidx.test.core.ktx)
}
