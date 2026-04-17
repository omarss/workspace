import java.util.Properties

plugins {
    alias(libs.plugins.omono.android.application)
    alias(libs.plugins.omono.android.compose)
    alias(libs.plugins.omono.android.hilt)
}

// Optional release signing. Drop a keystore.properties next to this file
// (gitignored) with: storeFile, storePassword, keyAlias, keyPassword.
// Generate a keystore via `make release-keystore`. Without it, release
// builds are signed with the debug key — fine for personal sideload via
// Obtainium since the cert just needs to be stable across releases.
val keystorePropsFile = rootProject.file("app/keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.exists()) load(keystorePropsFile.inputStream())
}

// Third-party API keys live in the gitignored local.properties at the
// repo root. Missing keys fall back to an empty string — features that
// need them show an empty state with a pointer to README.
val rootLocalProps = Properties().apply {
    rootProject.file("local.properties").takeIf { it.exists() }
        ?.inputStream()?.use { load(it) }
}
val tomtomApiKey: String = rootLocalProps.getProperty("tomtom.api.key", "")
// Self-hosted Google Places proxy (gplaces_parser backend). When both
// URL and key are present, DI uses this instead of TomTom for POI
// lookups. Both default to empty so a fresh clone still builds.
val gplacesApiUrl: String = rootLocalProps.getProperty("gplaces.api.url", "")
val gplacesApiKey: String = rootLocalProps.getProperty("gplaces.api.key", "")

android {
    namespace = "net.omarss.omono"

    defaultConfig {
        applicationId = "net.omarss.omono"
        versionCode = 23
        versionName = "0.16.0"

        buildConfigField("String", "TOMTOM_API_KEY", "\"${tomtomApiKey}\"")
        buildConfigField("String", "GPLACES_API_URL", "\"${gplacesApiUrl}\"")
        buildConfigField("String", "GPLACES_API_KEY", "\"${gplacesApiKey}\"")
    }

    buildFeatures {
        buildConfig = true
    }

    signingConfigs {
        if (keystoreProps.isNotEmpty()) {
            create("release") {
                storeFile = file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            // Minification is off until we lock down the Proguard rules
            // for Hilt + Compose. Re-enable once a release smoke-test
            // confirms reflective code paths still work.
            isMinifyEnabled = false
            isShrinkResources = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            signingConfig = if (keystoreProps.isNotEmpty()) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
        debug {
            applicationIdSuffix = ".debug"
        }
    }

    packaging {
        resources.excludes += setOf(
            "/META-INF/{AL2.0,LGPL2.1}",
            "/META-INF/DEPENDENCIES",
            "/META-INF/LICENSE*",
            "/META-INF/NOTICE*",
        )
    }
}

dependencies {
    implementation(projects.core.common)
    implementation(projects.core.data)
    implementation(projects.core.designsystem)
    implementation(projects.core.notification)
    implementation(projects.core.service)
    implementation(projects.feature.speed)
    implementation(projects.feature.spending)
    implementation(projects.feature.places)
    implementation(projects.feature.selfupdate)

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.compose.material.icons.extended)
    implementation(libs.hilt.navigation.compose)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.coroutines.play.services)
    implementation(libs.play.services.location)
    implementation(libs.accompanist.permissions)
    implementation(libs.timber)
}
