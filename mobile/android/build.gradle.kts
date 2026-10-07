import com.android.build.api.variant.ApplicationAndroidComponentsExtension
import com.android.build.api.variant.LibraryAndroidComponentsExtension

allprojects {
    repositories {
        google()
        mavenCentral()
        maven(url = "https://developer.huawei.com/repo/")
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
    // Some Flutter plugins still declare compileSdk 35 even though their
    // resolved Android AAR graph requires API 36. Plugin-application callbacks
    // run before a plugin's own android {} block can finish and may therefore
    // be overwritten. finalizeDsl runs after each Android build script has
    // configured its DSL but before variants/tasks are created, so API 36 is
    // the final compileSdk seen by AAR metadata validation.
    pluginManager.withPlugin("com.android.application") {
        extensions.configure<ApplicationAndroidComponentsExtension> {
            finalizeDsl { extension ->
                extension.compileSdk = 36
            }
        }
    }

    pluginManager.withPlugin("com.android.library") {
        extensions.configure<LibraryAndroidComponentsExtension> {
            finalizeDsl { extension ->
                extension.compileSdk = 36
            }
        }
    }

    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
