plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.kpcl.plantalert"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.kpcl.plantalert"
        minSdk = 26
        targetSdk = 34
        versionCode = 6
        versionName = "2.1"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // debug key so the release APK is installable without a keystore (prototype)
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // JVM unit tests only (the app itself has no third-party libraries); org.json gives the tests the
    // real JSON parser that android.jar only stubs
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
