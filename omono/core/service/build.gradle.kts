plugins {
    alias(libs.plugins.omono.android.library)
    alias(libs.plugins.omono.android.hilt)
}

android {
    namespace = "net.omarss.omono.core.service"
}

dependencies {
    implementation(projects.core.common)
    implementation(projects.core.notification)
    implementation(libs.androidx.lifecycle.service)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.timber)
}
