plugins {
    alias(libs.plugins.omono.android.library)
    alias(libs.plugins.omono.android.hilt)
}

android {
    namespace = "net.omarss.omono.core.data"
}

dependencies {
    implementation(projects.core.common)
    // api: features that depend on :core:data should see DataStore types
    // (Preferences, edit, stringPreferencesKey) without re-declaring the dep.
    api(libs.androidx.datastore.preferences)
    implementation(libs.kotlinx.coroutines.android)
}
