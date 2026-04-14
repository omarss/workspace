plugins {
    alias(libs.plugins.omono.android.feature)
}

android {
    namespace = "net.omarss.omono.feature.speed"
}

dependencies {
    implementation(projects.core.data)
    implementation(projects.core.notification)
    implementation(libs.play.services.location)
    implementation(libs.kotlinx.coroutines.play.services)
    implementation(libs.timber)
}
