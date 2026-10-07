"""Static APP-ID-001 gate for repository identity and stable native protocols."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ID = "com.jiyidays"
OLD_ID = ".".join(("cn", "jiyidashi", "jiyidashi"))
OLD_PACKAGE_PATH = "/".join(("cn", "jiyidashi", "jiyidashi"))


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str) -> None:
    value = text(path)
    if needle not in value:
        raise AssertionError(f"{path} is missing {needle!r}")


def forbid(path: str, needle: str) -> None:
    value = text(path)
    if needle in value:
        raise AssertionError(f"{path} still contains {needle!r}")


def main() -> None:
    android_gradle = "android/app/build.gradle.kts"
    ios_project = "ios/Runner.xcodeproj/project.pbxproj"
    info_plist = "ios/Runner/Info.plist"
    app_delegate = "ios/Runner/AppDelegate.swift"

    require(android_gradle, f'namespace = "{APP_ID}"')
    require(android_gradle, f'applicationId = "{APP_ID}"')
    require(ios_project, f"PRODUCT_BUNDLE_IDENTIFIER = {APP_ID};")
    require(ios_project, f"PRODUCT_BUNDLE_IDENTIFIER = {APP_ID}.RunnerTests;")
    require(info_plist, f"<string>{APP_ID}.passive-recovery</string>")
    require(app_delegate, f'identifier = "{APP_ID}.passive-recovery"')

    identity_files = [
        android_gradle,
        ios_project,
        info_plist,
        app_delegate,
        "android/app/src/main/AndroidManifest.xml",
        "ios/Runner/DebugProfile.entitlements",
        "ios/Runner/Release.entitlements",
    ]
    for path in identity_files:
        forbid(path, OLD_ID)

    production_root = ROOT / "android/app/src/main/kotlin" / Path(*APP_ID.split("."))
    test_root = ROOT / "android/app/src/test/kotlin" / Path(*APP_ID.split("."))
    old_production_root = ROOT / "android/app/src/main/kotlin" / Path(*OLD_PACKAGE_PATH.split("/"))
    old_test_root = ROOT / "android/app/src/test/kotlin" / Path(*OLD_PACKAGE_PATH.split("/"))
    if not production_root.is_dir() or not test_root.is_dir():
        raise AssertionError("Android production/test Kotlin package roots are missing")
    if old_production_root.exists() or old_test_root.exists():
        raise AssertionError("Old Android Kotlin package path still exists")

    kotlin_files = list(production_root.glob("*.kt")) + list(test_root.glob("*.kt"))
    if not kotlin_files:
        raise AssertionError("No migrated Kotlin files found")
    for path in kotlin_files:
        if not path.read_text(encoding="utf-8").startswith(f"package {APP_ID}\n"):
            raise AssertionError(f"{path} has an unexpected Kotlin package declaration")

    # These names are stable Flutter/native protocol identifiers, not app identity.
    require("lib/native_location_bridge.dart", "cn.jiyidashi/native_location")
    require("lib/native_motion_sampling_bridge.dart", "cn.jiyidashi/native_location")
    require("lib/main.dart", "cn.jiyidashi/passive_recovery")
    forbid("lib/native_location_bridge.dart", f"{APP_ID}/native_location")
    forbid("lib/main.dart", f"{APP_ID}/passive_recovery")

    print("APP-ID-001 static identity gate: PASS")
    print(f"Android/iOS app identity: {APP_ID}")
    print("Stable MethodChannel names: preserved")


if __name__ == "__main__":
    main()
