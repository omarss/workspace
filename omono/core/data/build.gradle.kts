plugins {
    alias(libs.plugins.omono.android.library)
    alias(libs.plugins.omono.android.hilt)
}

android {
    namespace = "net.omarss.omono.core.data"
}

dependencies {
    implementation(projects.core.common)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.kotlinx.coroutines.android)
}
