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

fun signingInput(propertyName: String, environmentName: String): String? =
    providers.gradleProperty(propertyName)
        .orElse(providers.environmentVariable(environmentName))
        .orNull
        ?.takeIf(String::isNotBlank)

val releaseStoreFile = signingInput(
    "android.release.storeFile",
    "ANDROID_RELEASE_KEYSTORE_PATH",
)
val releaseStorePassword = signingInput(
    "android.release.storePassword",
    "ANDROID_RELEASE_KEYSTORE_PASSWORD",
)
val releaseKeyAlias = signingInput(
    "android.release.keyAlias",
    "ANDROID_RELEASE_KEY_ALIAS",
)
val releaseKeyPassword = signingInput(
    "android.release.keyPassword",
    "ANDROID_RELEASE_KEY_PASSWORD",
)
val releaseSigningInputs = listOf(
    releaseStoreFile,
    releaseStorePassword,
    releaseKeyAlias,
    releaseKeyPassword,
)
val releaseSigningConfigured = releaseSigningInputs.all { it != null }
val releaseSigningPartiallyConfigured = releaseSigningInputs.any { it != null } &&
    !releaseSigningConfigured
if (releaseSigningPartiallyConfigured) {
    throw GradleException(
        "Android release signing requires keystore path, store password, key alias, and key password together."
    )
}
val productionSigningRequired = providers.gradleProperty("requireProductionSigning")
    .map(String::toBoolean)
    .orElse(false)
    .get()
if (productionSigningRequired && !releaseSigningConfigured) {
    throw GradleException(
        "Production signing is required, but no complete Android release signing configuration was provided."
    )
}

val pnvsSchemeIdentifier = externalPushValue("JIYI_PNVS_SCHEME_ID")
val productionPhoneOneTapRequired = providers.gradleProperty("requireProductionPhoneOneTap")
    .map(String::toBoolean)
    .orElse(providers.environmentVariable("JIYI_PHONE_ONE_TAP_PRODUCTION_REQUIRED")
        .map(String::toBoolean))
    .orElse(productionSigningRequired)
    .orElse(false)
    .get()
if (productionPhoneOneTapRequired && pnvsSchemeIdentifier.isBlank()) {
    throw GradleException(
        "Production phone one-tap requires JIYI_PNVS_SCHEME_ID; no provider scheme is configured."
    )
}

val wechatAppId = externalPushValue("JIYI_WECHAT_APP_ID")
val wechatProvider = externalPushValue("AUTH_WECHAT_PROVIDER").ifBlank { "disabled" }
val wechatLiveEnabled = externalPushValue("JIYI_WECHAT_LIVE_ENABLED").toBoolean()
if (wechatLiveEnabled && !wechatProvider.equals("wechat", ignoreCase = true)) {
    throw GradleException(
        "WeChat live mode requires AUTH_WECHAT_PROVIDER=wechat; production remains disabled by default."
    )
}
if (wechatLiveEnabled && wechatAppId.isBlank()) {
    throw GradleException(
        "WeChat live mode requires JIYI_WECHAT_APP_ID; no AppID is configured."
    )
}

android {
    namespace = "com.jiyidays"
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
        applicationId = "com.jiyidays"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = 24
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
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
        // This is a provider-issued client configuration identifier, never a server credential.
        // The default is intentionally empty; the native adapter remains fail closed.
        buildConfigField("String", "JIYI_PNVS_SCHEME_ID", quotedBuildConfig(pnvsSchemeIdentifier))
        buildConfigField(
            "Boolean",
            "JIYI_PHONE_ONE_TAP_PRODUCTION_REQUIRED",
            productionPhoneOneTapRequired.toString(),
        )
        buildConfigField("String", "JIYI_WECHAT_APP_ID", quotedBuildConfig(wechatAppId))
        buildConfigField("String", "AUTH_WECHAT_PROVIDER", quotedBuildConfig(wechatProvider))
        buildConfigField("Boolean", "JIYI_WECHAT_LIVE_ENABLED", wechatLiveEnabled.toString())
        manifestPlaceholders["JIYI_HMS_APP_ID"] = hmsAppId
        if (fcmAppId.isNotBlank()) {
            resValue("string", "google_app_id", fcmAppId)
            resValue("string", "gcm_defaultSenderId", fcmSenderId)
            resValue("string", "google_api_key", fcmApiKey)
            resValue("string", "project_id", fcmProjectId)
        }
    }

    signingConfigs {
        if (releaseSigningConfigured) {
            create("release") {
                storeFile = file(requireNotNull(releaseStoreFile))
                storePassword = requireNotNull(releaseStorePassword)
                keyAlias = requireNotNull(releaseKeyAlias)
                keyPassword = requireNotNull(releaseKeyPassword)
            }
        }
    }

    buildTypes {
        release {
            // Production signing is attached only when all four secret inputs are supplied.
            // Without them this remains an intentionally unsigned release artifact; it never
            // falls back to the debug key.
            if (releaseSigningConfigured) {
                signingConfig = signingConfigs.getByName("release")
            }
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }
}

tasks.register("verifyReleaseSigningConfiguration") {
    doLast {
        val releaseSigningName = android.buildTypes.getByName("release").signingConfig?.name
        check(releaseSigningName != "debug") {
            "Release signing must never use the debug signing key."
        }
        if (releaseSigningConfigured) {
            println("ANDROID_RELEASE_SIGNING=CONFIGURED")
        } else {
            println("ANDROID_RELEASE_SIGNING=INFRA READY / KEY MATERIAL PENDING")
            println("Release verification artifact is intentionally unsigned; production signing is gated.")
        }
    }
}

tasks.register("verifyPhoneOneTapProductionConfiguration") {
    doLast {
        check(android.defaultConfig.applicationId == "com.jiyidays") {
            "Phone one-tap production requires Android applicationId com.jiyidays."
        }
        if (productionPhoneOneTapRequired) {
            check(pnvsSchemeIdentifier.isNotBlank()) {
                "Production phone one-tap requires JIYI_PNVS_SCHEME_ID; no provider scheme is configured."
            }
            check(releaseSigningConfigured) {
                "Production phone one-tap requires complete Android release signing configuration."
            }
            println("ANDROID_PHONE_ONE_TAP_PRODUCTION_CONFIG=READY_FOR_EXTERNAL_PROVIDER_REVIEW")
        } else {
            println("ANDROID_PHONE_ONE_TAP_PRODUCTION_CONFIG=FAIL_CLOSED_UNTIL_EXPLICITLY_REQUIRED")
        }
    }
}

tasks.configureEach {
    if (name == "assembleRelease") {
        dependsOn("verifyReleaseSigningConfiguration")
        dependsOn("verifyPhoneOneTapProductionConfiguration")
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
    // Locked official WeChat OpenSDK artifact; defaults remain disabled/fail closed.
    implementation("com.tencent.mm.opensdk:wechat-sdk-android:6.8.40")
    testImplementation("junit:junit:4.13.2")
}

flutter {
    source = "../.."
}
