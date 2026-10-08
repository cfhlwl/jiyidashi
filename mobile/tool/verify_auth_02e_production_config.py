"""AUTH-02E static and fail-closed production configuration gate."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ID = "com.jiyidays"
FINGERPRINT_RE = re.compile(r"^[0-9A-Fa-f]{64}$")


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
    require("ios/Runner/AppDelegate.swift", "PhoneOneTapProviderConfiguration")
    print("AUTH-02E static production configuration seam: PASS")
    print("PHONE_ONE_TAP_LIVE_PROVIDER: DISABLED (fail closed; no real SDK/credential)")


def first_missing_production_requirement() -> str | None:
    requirements = (
        ("JIYI_ANDROID_PNVS_SCHEME_ID or JIYI_PNVS_SCHEME_ID", "JIYI_ANDROID_PNVS_SCHEME_ID", "JIYI_PNVS_SCHEME_ID"),
        ("JIYI_IOS_PNVS_SCHEME_ID or JIYI_PNVS_SCHEME_ID", "JIYI_IOS_PNVS_SCHEME_ID", "JIYI_PNVS_SCHEME_ID"),
        ("ANDROID_RELEASE_KEYSTORE_PATH", "ANDROID_RELEASE_KEYSTORE_PATH"),
        ("ANDROID_RELEASE_KEYSTORE_PASSWORD", "ANDROID_RELEASE_KEYSTORE_PASSWORD"),
        ("ANDROID_RELEASE_KEY_ALIAS", "ANDROID_RELEASE_KEY_ALIAS"),
        ("ANDROID_RELEASE_KEY_PASSWORD", "ANDROID_RELEASE_KEY_PASSWORD"),
        ("ANDROID_RELEASE_CERTIFICATE_SHA256", "ANDROID_RELEASE_CERTIFICATE_SHA256"),
        ("APPLE_TEAM_ID", "APPLE_TEAM_ID"),
    )
    for item in requirements:
        label, *names = item
        if not any(os.environ.get(name, "").strip() for name in names):
            return label

    fingerprint = os.environ["ANDROID_RELEASE_CERTIFICATE_SHA256"].strip()
    if not FINGERPRINT_RE.fullmatch(fingerprint):
        return "ANDROID_RELEASE_CERTIFICATE_SHA256 (64 hexadecimal characters)"
    return None


def production_gate() -> None:
    missing = first_missing_production_requirement()
    if missing:
        raise RuntimeError(
            "AUTH-02E production gate blocked: missing required external/configuration "
            f"input {missing}. No provider secret was read or printed."
        )
    print("AUTH-02E production configuration: READY_FOR_EXTERNAL_PROVIDER_REVIEW")


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
