"""AUTH-02E iOS Release build-consumed production gate."""

from __future__ import annotations

import argparse


APP_ID = "com.jiyidays"


def is_required(value: str) -> bool:
    return value.strip().lower() in {"yes", "true", "1"}


def is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        not normalized
        or "$(" in normalized
        or normalized in {"placeholder", "changeme", "example", "none"}
    )


def validate(
    *,
    required: str,
    bundle_id: str,
    scheme_id: str,
    team_id: str,
    expected_team_id: str,
) -> None:
    if not is_required(required):
        print("AUTH-02E iOS production gate: DISABLED (runtime remains fail closed)")
        return
    if bundle_id.strip() != APP_ID:
        raise RuntimeError(
            "AUTH-02E iOS production gate blocked: "
            f"PRODUCT_BUNDLE_IDENTIFIER must be {APP_ID}."
        )
    if is_placeholder(scheme_id):
        raise RuntimeError(
            "AUTH-02E iOS production gate blocked: "
            "JIYI_PNVS_SCHEME_ID is empty or a build-setting placeholder."
        )
    if is_placeholder(team_id):
        raise RuntimeError(
            "AUTH-02E iOS production gate blocked: DEVELOPMENT_TEAM is missing."
        )
    if is_placeholder(expected_team_id):
        raise RuntimeError(
            "AUTH-02E iOS production gate blocked: "
            "JIYI_APPLE_DEVELOPMENT_TEAM is missing."
        )
    if team_id.strip() != expected_team_id.strip():
        raise RuntimeError(
            "AUTH-02E iOS production gate blocked: DEVELOPMENT_TEAM does not match "
            "JIYI_APPLE_DEVELOPMENT_TEAM."
        )
    print("AUTH-02E iOS production gate: build-consumed configuration PASS")
    print("AUTH-02E iOS production status: CODE READY / EXTERNAL BLOCKED")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--required", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--scheme-id", required=True)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--expected-team-id", required=True)
    args = parser.parse_args()
    validate(
        required=args.required,
        bundle_id=args.bundle_id,
        scheme_id=args.scheme_id,
        team_id=args.team_id,
        expected_team_id=args.expected_team_id,
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1)
