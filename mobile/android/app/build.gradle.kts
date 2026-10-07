plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

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

android {
    namespace = "com.jiyidays"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
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

tasks.configureEach {
    if (name == "assembleRelease") {
        dependsOn("verifyReleaseSigningConfiguration")
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

dependencies {
    implementation("androidx.work:work-runtime:2.9.1")
    testImplementation("junit:junit:4.13.2")
}

flutter {
    source = "../.."
}
