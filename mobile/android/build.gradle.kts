import com.android.build.api.dsl.ApplicationExtension
import com.android.build.api.dsl.LibraryExtension

allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")

    // AMap's Flutter bridge still declares compileSdk 35, while its resolved
    // Android AAR graph requires API 36. Keep every Android module on one
    // compile SDK so third-party plugin metadata validation cannot drift.
    afterEvaluate {
        when {
            plugins.hasPlugin("com.android.application") ->
                extensions.configure<ApplicationExtension> {
                    compileSdk = 36
                }

            plugins.hasPlugin("com.android.library") ->
                extensions.configure<LibraryExtension> {
                    compileSdk = 36
                }
        }
    }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
