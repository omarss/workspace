plugins {
    alias(libs.plugins.omono.android.library)
    alias(libs.plugins.omono.android.hilt)
}

android {
    namespace = "net.omarss.omono.core.notification"
}

dependencies {
    implementation(projects.core.common)
    implementation(libs.androidx.core.ktx)
}
