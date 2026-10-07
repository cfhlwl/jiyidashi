plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

fun externalPushValue(name: String): String =
    providers.gradleProperty(name)
        .orElse(providers.environmentVariable(name))
        .orElse("")
        .get()

fun quotedBuildConfig(value: String): String =
    "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

android {
    namespace = "cn.jiyidashi.jiyidashi"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }

    defaultConfig {
        // Historical identity remains unchanged until APP-ID-001 is authoritative.
        applicationId = "cn.jiyidashi.jiyidashi"
        minSdk = 24
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName

        val fcmProjectId = externalPushValue("JIYI_FCM_PROJECT_ID")
        val fcmAppId = externalPushValue("JIYI_FCM_APP_ID")
        val fcmApiKey = externalPushValue("JIYI_FCM_API_KEY")
        val fcmSenderId = externalPushValue("JIYI_FCM_SENDER_ID")
        val hmsAppId = externalPushValue("JIYI_HMS_APP_ID")
        buildConfigField("String", "JIYI_FCM_PROJECT_ID", quotedBuildConfig(fcmProjectId))
        buildConfigField("String", "JIYI_FCM_APP_ID", quotedBuildConfig(fcmAppId))
        buildConfigField("String", "JIYI_FCM_API_KEY", quotedBuildConfig(fcmApiKey))
        buildConfigField("String", "JIYI_FCM_SENDER_ID", quotedBuildConfig(fcmSenderId))
        buildConfigField("String", "JIYI_HMS_APP_ID", quotedBuildConfig(hmsAppId))
        manifestPlaceholders["JIYI_HMS_APP_ID"] = hmsAppId
    }

    buildTypes {
        release {
            // Release signing authority remains outside NOTIFY-001B.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

dependencies {
    implementation("androidx.work:work-runtime:2.9.1")
    implementation(platform("com.google.firebase:firebase-bom:34.19.0"))
    implementation("com.google.firebase:firebase-messaging")
    implementation("com.huawei.hms:push:6.13.0.300")
    testImplementation("junit:junit:4.13.2")
}

flutter {
    source = "../.."
}
