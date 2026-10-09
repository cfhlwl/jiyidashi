"""AUTH-02E static and fail-closed production configuration gate."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ID = "com.jiyidays"
FINGERPRINT_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
KEYTOOL_FINGERPRINT_RE = re.compile(r"SHA256:\s*([0-9A-Fa-f: ]+)", re.IGNORECASE)


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def require(relative: str, needle: str) -> None:
    if needle not in read(relative):
        raise RuntimeError(f"{relative} is missing required AUTH-02E seam: {needle}")


def static_gate() -> None:
    require("android/app/build.gradle.kts", f'namespace = "{APP_ID}"')
    require("android/app/build.gradle.kts", f'applicationId = "{APP_ID}"')
    require("android/app/build.gradle.kts", 'buildConfigField("String", "JIYI_PNVS_SCHEME_ID"')
    require("android/app/build.gradle.kts", "verifyPhoneOneTapProductionConfiguration")
    require("android/app/build.gradle.kts", "Production signing is required")
    require("android/app/src/main/kotlin/com/jiyidays/PhoneOneTapNativeAdapter.kt", "PNVS_CONFIGURATION_MISSING")
    require("ios/Runner.xcodeproj/project.pbxproj", f"PRODUCT_BUNDLE_IDENTIFIER = {APP_ID};")
    require("ios/Runner/Info.plist", "JIYI_PNVS_SCHEME_ID")
    require("ios/Runner/Info.plist", "JIYI_PHONE_ONE_TAP_PRODUCTION_REQUIRED")
    require("ios/Flutter/Release.xcconfig", "JIYI_PNVS_SCHEME_ID")
    require("ios/Flutter/Release.xcconfig", "DEVELOPMENT_TEAM = $(JIYI_APPLE_DEVELOPMENT_TEAM)")
    require("ios/Runner.xcodeproj/project.pbxproj", "AUTH-02E Production Gate")
    require("ios/Runner.xcodeproj/project.pbxproj", "verify_auth_02e_ios_release_config.py")
    require("ios/Runner/AppDelegate.swift", "PhoneOneTapProviderConfiguration")
    print("AUTH-02E static production configuration seam: PASS")
    print("PHONE_ONE_TAP_LIVE_PROVIDER: DISABLED (fail closed; no real SDK/credential)")


def first_missing_production_requirement() -> str | None:
    requirements = (
        ("JIYI_PNVS_SCHEME_ID", "JIYI_PNVS_SCHEME_ID"),
        ("ANDROID_RELEASE_KEYSTORE_PATH", "ANDROID_RELEASE_KEYSTORE_PATH"),
        ("ANDROID_RELEASE_KEYSTORE_PASSWORD", "ANDROID_RELEASE_KEYSTORE_PASSWORD"),
        ("ANDROID_RELEASE_KEY_ALIAS", "ANDROID_RELEASE_KEY_ALIAS"),
        ("ANDROID_RELEASE_KEY_PASSWORD", "ANDROID_RELEASE_KEY_PASSWORD"),
        ("ANDROID_RELEASE_CERTIFICATE_SHA256", "ANDROID_RELEASE_CERTIFICATE_SHA256"),
        ("JIYI_APPLE_DEVELOPMENT_TEAM", "JIYI_APPLE_DEVELOPMENT_TEAM"),
    )
    for item in requirements:
        label, *names = item
        if not any(os.environ.get(name, "").strip() for name in names):
            return label

    return None


def production_gate() -> None:
    missing = first_missing_production_requirement()
    if missing:
        raise RuntimeError(
            "AUTH-02E production gate blocked: missing required external/configuration "
            f"input {missing}. No provider secret was read or printed."
        )
    expected = os.environ["ANDROID_RELEASE_CERTIFICATE_SHA256"].strip().upper()
    if not FINGERPRINT_RE.fullmatch(expected):
        raise RuntimeError(
            "AUTH-02E Android production gate blocked: "
            "ANDROID_RELEASE_CERTIFICATE_SHA256 must be 64 hexadecimal characters."
        )
    try:
        derived = derive_android_certificate_fingerprint(
            keystore_path=os.environ["ANDROID_RELEASE_KEYSTORE_PATH"],
            store_password=os.environ["ANDROID_RELEASE_KEYSTORE_PASSWORD"],
            alias=os.environ["ANDROID_RELEASE_KEY_ALIAS"],
            key_password=os.environ["ANDROID_RELEASE_KEY_PASSWORD"],
        )
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(
            "AUTH-02E Android production gate blocked: "
            "unable to derive the release certificate fingerprint from the supplied keystore."
        ) from exc
    if derived != expected:
        raise RuntimeError(
            "AUTH-02E Android production gate blocked: release certificate fingerprint mismatch "
            f"(expected {expected}, derived {derived})."
        )
    print("AUTH-02E Android production config: certificate fingerprint comparison PASS")
    print("AUTH-02E production configuration: CODE READY / EXTERNAL BLOCKED")


def derive_android_certificate_fingerprint(
    *,
    keystore_path: str,
    store_password: str,
    alias: str,
    key_password: str,
) -> str:
    if not keystore_path.strip() or not Path(keystore_path).is_file():
        raise RuntimeError("keystore is missing")
    command = [
        "keytool",
        "-list",
        "-v",
        "-keystore",
        keystore_path,
        "-alias",
        alias,
        "-storepass:env",
        "AUTH02E_KEYSTORE_PASSWORD",
        "-keypass:env",
        "AUTH02E_KEY_PASSWORD",
    ]
    keytool_environment = os.environ.copy()
    keytool_environment["AUTH02E_KEYSTORE_PASSWORD"] = store_password
    keytool_environment["AUTH02E_KEY_PASSWORD"] = key_password
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=keytool_environment,
    )
    if result.returncode != 0:
        raise RuntimeError("keytool failed")
    match = KEYTOOL_FINGERPRINT_RE.search(result.stdout + result.stderr)
    if not match:
        raise RuntimeError("keytool did not return SHA256 fingerprint")
    fingerprint = re.sub(r"[^0-9A-Fa-f]", "", match.group(1)).upper()
    if not FINGERPRINT_RE.fullmatch(fingerprint):
        raise RuntimeError("keytool returned malformed SHA256 fingerprint")
    return fingerprint


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-production", action="store_true")
    args = parser.parse_args()
    static_gate()
    if args.require_production:
        production_gate()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1)
