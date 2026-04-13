plugins {
    alias(libs.plugins.omono.android.library)
    alias(libs.plugins.omono.android.compose)
}

android {
    namespace = "net.omarss.omono.core.designsystem"
}

dependencies {
    implementation(libs.androidx.compose.material.icons.extended)
}
