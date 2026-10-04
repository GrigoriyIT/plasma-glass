import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

// release key lives outside the repo: keystore.properties (storeFile, storePassword, keyAlias, keyPassword)
val keystore = rootProject.file("keystore.properties").takeIf { it.exists() }?.let { f ->
    Properties().apply { f.inputStream().use { load(it) } }
}

android {
    namespace = "local.glassvpn"
    compileSdk { version = release(37) }

    defaultConfig {
        applicationId = "local.glassvpn"
        minSdk = 28          // Android 9 (e.g. Xiaomi TV Box S); see the manifest for hev
        targetSdk = 36
        versionCode = 10
        versionName = "1.8"
    }

    signingConfigs {
        if (keystore != null) create("release") {
            storeFile = file(keystore.getProperty("storeFile"))
            storePassword = keystore.getProperty("storePassword")
            keyAlias = keystore.getProperty("keyAlias")
            keyPassword = keystore.getProperty("keyPassword")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (keystore != null) signingConfig = signingConfigs.getByName("release")
        }
    }

    // one APK per ABI: the Xray library alone is ~35 MB per architecture
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a", "x86_64", "x86")
            isUniversalApk = false
        }
    }

    packaging {
        jniLibs.useLegacyPackaging = true
    }

    buildFeatures {
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.aar"))))

    implementation(platform("androidx.compose:compose-bom:2026.09.00"))
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-core")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.11.0")
    implementation("com.google.zxing:core:3.5.4")   // QR code for adding a subscription from a phone (TV)

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20260814")
}
