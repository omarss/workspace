plugins {
    alias(libs.plugins.omono.android.library)
}

android {
    namespace = "net.omarss.omono.core.common"
}

dependencies {
    implementation(libs.kotlinx.coroutines.android)
}
