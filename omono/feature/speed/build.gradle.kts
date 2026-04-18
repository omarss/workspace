plugins {
    alias(libs.plugins.omono.android.feature)
}

android {
    namespace = "net.omarss.omono.feature.speed"

    // AIDL is off by default in AGP 8+. Re-enabled here for the
    // Shizuku InternetUserService binding — the stub + proxy the
    // IInternetService.aidl file compiles into is how the main
    // process talks to the user-service process over binder.
    buildFeatures {
        aidl = true
    }

    testOptions {
        unitTests {
            isIncludeAndroidResources = true
        }
    }
}

dependencies {
    implementation(projects.core.data)
    implementation(projects.core.notification)
    implementation(libs.play.services.location)
    implementation(libs.kotlinx.coroutines.play.services)
    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
    ksp(libs.androidx.room.compiler)
    implementation(libs.shizuku.api)
    implementation(libs.shizuku.provider)
    implementation(libs.timber)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.turbine)
    testImplementation(libs.kotest.assertions.core)
    testImplementation(libs.robolectric)
    testImplementation(libs.androidx.test.core.ktx)
}
