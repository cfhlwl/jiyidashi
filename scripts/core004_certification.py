#!/usr/bin/env python3
"""CORE-004 real-device certification evidence validator.

This tool validates the certification contract and privacy-safe evidence metadata.
It deliberately does not manufacture physical-device evidence or infer PASS from CI.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
EMAIL_RE = re.compile(r"(?i)\\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}\\b")
BEARER_RE = re.compile(r"(?i)\\bBearer\\s+[A-Za-z0-9._~+/=-]{8,}")
JWT_RE = re.compile(r"\\beyJ[A-Za-z0-9_-]{8,}\\.[A-Za-z0-9_-]{8,}\\.[A-Za-z0-9_-]{8,}\\b")
SENSITIVE_TEXT_KEY_RE = re.compile(
    r"(?i)\\b(latitude|longitude|access[_ -]?token|refresh[_ -]?token|authorization|"
    r"password|secret|imei|serial|device[_ -]?id|advertising[_ -]?id|ad[_ -]?id|email)\\b\\s*[:=]"
)

HEALTH_STATES = {"HEALTHY", "DEGRADED", "PAUSED", "BLOCKED", "RECOVERING", "UNKNOWN"}

ALLOWED_SCOPE_PREFIXES = (
    "docs/certification/core004/",
)
ALLOWED_SCOPE_EXACT = {
    ".github/workflows/core004-certification.yml",
    "docs/DEVELOPMENT_PROGRESS.md",
    "scripts/core004_certification.py",
    "scripts/test_core004_certification.py",
}


class ValidationError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"top-level JSON must be object: {path}")
    return data


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def parse_iso(value: Any, field: str) -> datetime:
    require(isinstance(value, str) and value, f"{field} must be a non-empty ISO timestamp")
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError(f"{field} is not valid ISO-8601: {value}") from exc
    require(dt.tzinfo is not None, f"{field} must include timezone/UTC offset")
    return dt


def iter_nodes(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_nodes(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_nodes(child, f"{path}[{index}]")


def privacy_guard_json(data: dict[str, Any], forbidden_keys: set[str], source: Path) -> None:
    for path, value in iter_nodes(data):
        if isinstance(value, dict):
            for key in value:
                if key.lower() in forbidden_keys:
                    raise ValidationError(f"{source}: forbidden privacy key at {path}.{key}")
        elif isinstance(value, str):
            if EMAIL_RE.search(value):
                raise ValidationError(f"{source}: email-like value forbidden at {path}")
            if BEARER_RE.search(value):
                raise ValidationError(f"{source}: bearer credential-like value forbidden at {path}")
            if JWT_RE.search(value):
                raise ValidationError(f"{source}: JWT-like value forbidden at {path}")


def privacy_guard_text(path: Path) -> None:
    if path.suffix.lower() not in {".md", ".txt", ".log", ".json", ".csv"}:
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    for label, pattern in (
        ("email-like value", EMAIL_RE),
        ("bearer credential-like value", BEARER_RE),
        ("JWT-like value", JWT_RE),
        ("sensitive key/value text", SENSITIVE_TEXT_KEY_RE),
    ):
        if pattern.search(text):
            raise ValidationError(f"{path}: {label} found; redact before committing")


def require_bool(checks: dict[str, Any], key: str, expected: bool = True) -> None:
    require(checks.get(key) is expected, f"checks.{key} must be {str(expected).lower()} for PASS")


def require_nonnegative_int(checks: dict[str, Any], key: str) -> int:
    value = checks.get(key)
    require(type(value) is int and value >= 0, f"checks.{key} must be a non-negative integer")
    return value


def validate_pass_checks(record: dict[str, Any], acceptance: dict[str, Any]) -> None:
    scenario = record["scenario_id"]
    checks = record.get("checks")
    require(isinstance(checks, dict), "checks must be an object for PASS evidence")

    thresholds = acceptance["frozen_v1_thresholds"]
    start = parse_iso(record["started_at_utc"], "started_at_utc")
    end = parse_iso(record["ended_at_utc"], "ended_at_utc")
    duration = (end - start).total_seconds()
    require(duration >= 0, "ended_at_utc must not precede started_at_utc")

    if scenario == "C1":
        require(duration >= thresholds["c1_min_duration_seconds"], "C1 PASS requires >=24h observation")
        require_bool(checks, "ui_opened_during_window", False)
        require_bool(checks, "server_side_passive_evidence")
        require_bool(checks, "recording_health_before_after")
        require_bool(checks, "movement_transition_or_stationary_segment_documented")
    elif scenario == "C2":
        require(duration >= thresholds["c2_min_duration_seconds"], "C2 PASS requires >=72h observation")
        require_bool(checks, "os_battery_evidence_attached")
        require_bool(checks, "runaway_drain_observed", False)
        require_bool(checks, "thermal_or_location_abuse_observed", False)
        require_bool(checks, "normal_use_practical")
        require_bool(checks, "visit_quality_documented")
        gap = require_nonnegative_int(checks, "max_unexplained_gap_seconds_while_authority_healthy")
        require(
            gap < thresholds["unexplained_loss_fail_seconds_while_authority_healthy"],
            "C2 FAIL threshold reached: unexplained multi-hour loss while authority is healthy",
        )
    elif scenario == "C3":
        offline = require_nonnegative_int(checks, "offline_duration_seconds")
        require(offline >= thresholds["c3_min_offline_duration_seconds"], "C3 PASS requires >=12h offline")
        for key in (
            "durable_queue_retained",
            "automatic_replay",
            "queue_drained",
            "server_ack_advanced",
            "day_footprint_retained",
        ):
            require_bool(checks, key)
        require(require_nonnegative_int(checks, "uuid_duplicate_count") == 0, "C3 duplicate UUID count must be 0")
    elif scenario == "C4":
        for key in (
            "platform_contract_documented",
            "force_stop_or_force_quit_distinguished",
            "no_false_healthy",
        ):
            require_bool(checks, key)
    elif scenario == "C5":
        for key in (
            "no_stale_owner_sampling",
            "platform_authorized_recovery",
            "no_duplicate_uuid",
            "health_truthful",
        ):
            require_bool(checks, key)
    elif scenario == "C6":
        for key in (
            "paused_state_observed",
            "paused_interval_ingest_rejected",
            "no_fake_visit",
            "forbidden_paused_evidence_not_replayed",
            "post_resume_continues",
        ):
            require_bool(checks, key)
    elif scenario == "C7":
        for key in (
            "blocked_or_unknown_observed",
            "cta_matches_reason",
            "no_false_green",
            "recovery_owner_safe",
        ):
            require_bool(checks, key)
    elif scenario == "C8":
        require(require_nonnegative_int(checks, "provider_call_count") == 0, "C8 provider_call_count must be 0")
        for key in ("deterministic_date", "footprint_compared_to_actual"):
            require_bool(checks, key)
        for key in ("false_positive_count", "false_negative_count", "ordering_discrepancy_count"):
            require_nonnegative_int(checks, key)
    elif scenario == "C9":
        for key in (
            "evidence_trace_complete",
            "no_unsupported_personal_fact",
            "provider_unavailable_fallback",
            "no_evidence_no_invention",
        ):
            require_bool(checks, key)
    elif scenario == "C10":
        require(require_nonnegative_int(checks, "false_green_count") == 0, "C10 false_green_count must be 0")
        require_bool(checks, "malformed_state_never_green")
        coverage = checks.get("health_state_coverage")
        require(isinstance(coverage, dict), "C10 checks.health_state_coverage must be an object")
        require(set(coverage) == HEALTH_STATES, "C10 health_state_coverage must address all six health states")
        for state, proof_or_reason in coverage.items():
            require(
                isinstance(proof_or_reason, str) and proof_or_reason.strip(),
                f"C10 health_state_coverage.{state} must contain evidence path or explicit not-observed reason",
            )
    elif scenario == "OWNER_SESSION":
        for key in (
            "owner_a_queue_not_published_as_b",
            "late_a_health_not_rendered_for_b",
            "owner_b_has_no_a_visit_place_health",
            "old_authority_invalidated",
        ):
            require_bool(checks, key)


def validate_evidence_record(
    path: Path,
    entry: dict[str, Any],
    acceptance: dict[str, Any],
    forbidden_keys: set[str],
) -> None:
    record = load_json(path)
    privacy_guard_json(record, forbidden_keys, path)

    required = {
        "schema_version", "issue", "run_id", "scenario_id", "platform", "result",
        "git_head", "app_build", "device", "environment",
        "started_at_local", "ended_at_local", "started_at_utc", "ended_at_utc",
        "preconditions", "actions", "expected", "observed",
        "health_snapshots", "day_footprint_evidence", "queue_evidence",
        "battery_evidence", "attachments", "checks", "notes",
    }
    missing = sorted(required - set(record))
    require(not missing, f"{path}: missing required fields: {', '.join(missing)}")
    require(record["schema_version"] == acceptance["schema_version"], f"{path}: schema_version mismatch")
    require(record["issue"] == acceptance["issue"], f"{path}: issue mismatch")
    require(record["scenario_id"] == entry["scenario_id"], f"{path}: scenario mismatch")
    require(record["platform"] == entry["platform"], f"{path}: platform mismatch")
    require(record["result"] == entry["result"], f"{path}: result must match matrix entry")
    require(HEX40_RE.fullmatch(record["git_head"] or "") is not None, f"{path}: git_head must be 40 lowercase hex")
    require(set(record["git_head"]) != {"0"}, f"{path}: placeholder git_head is forbidden")

    require(
        isinstance(record["run_id"], str) and record["run_id"] and path.stem == record["run_id"],
        f"{path}: run_id must exactly match evidence filename",
    )
    for key in ("preconditions", "actions", "expected", "observed", "health_snapshots",
                "day_footprint_evidence", "queue_evidence", "battery_evidence", "attachments"):
        require(isinstance(record[key], list), f"{path}: {key} must be an array")
    for key in ("app_build", "device", "environment", "checks"):
        require(isinstance(record[key], dict), f"{path}: {key} must be an object")

    local_start = parse_iso(record["started_at_local"], "started_at_local")
    local_end = parse_iso(record["ended_at_local"], "ended_at_local")
    utc_start = parse_iso(record["started_at_utc"], "started_at_utc")
    utc_end = parse_iso(record["ended_at_utc"], "ended_at_utc")
    require(local_end >= local_start, f"{path}: local end precedes start")
    require(utc_end >= utc_start, f"{path}: UTC end precedes start")
    require(
        local_start.astimezone(timezone.utc) == utc_start.astimezone(timezone.utc),
        f"{path}: local/UTC start timestamps disagree",
    )
    require(
        local_end.astimezone(timezone.utc) == utc_end.astimezone(timezone.utc),
        f"{path}: local/UTC end timestamps disagree",
    )

    if record["result"] == "PASS":
        validate_pass_checks(record, acceptance)


def validate_root(root: Path, progress_path: Path | None = None) -> dict[str, int]:
    acceptance = load_json(root / "acceptance.json")
    matrix = load_json(root / "matrix.json")

    require(acceptance.get("schema_version") == 1, "acceptance schema_version must be 1")
    require(acceptance.get("issue") == 190, "acceptance issue must be #190")
    require(
        acceptance.get("base_sha") == "b8d5a01c8b2329bdadd9ea63df59bc705d834add",
        "CORE-004 base SHA lock changed unexpectedly",
    )
    require(matrix.get("schema_version") == acceptance["schema_version"], "matrix schema_version mismatch")
    require(matrix.get("issue") == acceptance["issue"], "matrix issue mismatch")
    require(matrix.get("base_sha") == acceptance["base_sha"], "matrix base_sha mismatch")
    require(isinstance(matrix.get("entries"), list), "matrix.entries must be an array")

    platforms = acceptance["mandatory_platforms"]
    scenarios = acceptance["mandatory_scenarios"]
    allowed_results = set(acceptance["result_values"])
    expected_keys = {(scenario, platform) for scenario in scenarios for platform in platforms}
    seen: set[tuple[str, str]] = set()
    counts = {value: 0 for value in allowed_results}
    forbidden_keys = {x.lower() for x in acceptance["privacy"]["forbidden_keys"]}

    for entry in matrix["entries"]:
        require(isinstance(entry, dict), "matrix entry must be object")
        scenario = entry.get("scenario_id")
        platform = entry.get("platform")
        key = (scenario, platform)
        require(key in expected_keys, f"unexpected matrix entry: {key}")
        require(key not in seen, f"duplicate matrix entry: {key}")
        seen.add(key)

        result = entry.get("result")
        require(result in allowed_results, f"{key}: invalid result {result!r}")
        counts[result] += 1

        evidence = entry.get("evidence")
        require(isinstance(evidence, list), f"{key}: evidence must be array")
        if result in {"PASS", "FAIL"}:
            require(evidence, f"{key}: {result} requires preserved evidence")
        if result == "BLOCKED":
            require(
                isinstance(entry.get("blocker_code"), str) and entry["blocker_code"].strip()
                and isinstance(entry.get("blocker"), str) and entry["blocker"].strip(),
                f"{key}: BLOCKED requires blocker_code and blocker",
            )
        if result == "NOT_APPLICABLE":
            require(
                isinstance(entry.get("justification"), str) and entry["justification"].strip(),
                f"{key}: NOT_APPLICABLE requires platform-specific justification",
            )

        for rel in evidence:
            require(isinstance(rel, str) and rel.startswith("evidence/"), f"{key}: invalid evidence path {rel!r}")
            evidence_path = (root / rel).resolve()
            require(root.resolve() in evidence_path.parents, f"{key}: evidence path escapes root")
            require(evidence_path.is_file(), f"{key}: missing evidence file {rel}")
            validate_evidence_record(evidence_path, entry, acceptance, forbidden_keys)

    require(seen == expected_keys, f"matrix missing entries: {sorted(expected_keys - seen)}")

    evidence_root = root / "evidence"
    if evidence_root.exists():
        referenced = {
            (root / rel).resolve()
            for entry in matrix["entries"]
            for rel in entry.get("evidence", [])
        }
        for path in evidence_root.rglob("*"):
            if path.is_file():
                privacy_guard_text(path)
                if path.suffix.lower() == ".json":
                    require(path.resolve() in referenced, f"orphan evidence JSON not referenced by matrix: {path}")

    incomplete = counts["FAIL"] + counts["BLOCKED"] > 0
    expected_state = "ACTIVE" if incomplete else "EVIDENCE_COMPLETE"
    require(
        matrix.get("certification_state") == expected_state,
        f"matrix.certification_state must be {expected_state}",
    )

    if progress_path and progress_path.exists():
        progress = progress_path.read_text(encoding="utf-8")
        row = next((line for line in progress.splitlines() if "| CORE-004 |" in line), "")
        require(row, "CORE-004 progress row missing")
        if incomplete:
            require("| 🔵 |" in row, "CORE-004 must remain 🔵 while mandatory evidence is incomplete")
        else:
            require("| 🟠 |" in row, "CORE-004 must become 🟠 when mandatory evidence is complete")
        require("| ✅ |" not in row, "CORE-004 must not become ✅ before formal certification review + merge")

    return counts


def validate_scope(repo_root: Path, base_sha: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}...HEAD"],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )
    changed = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    invalid = [
        path for path in changed
        if path not in ALLOWED_SCOPE_EXACT and not path.startswith(ALLOWED_SCOPE_PREFIXES)
    ]
    require(
        not invalid,
        "CORE-004 evidence PR contains out-of-scope production changes: " + ", ".join(invalid),
    )
    return changed


def summary(root: Path) -> str:
    matrix = load_json(root / "matrix.json")
    lines = ["Scenario | Android | iOS", "--- | --- | ---"]
    by_key = {(e["scenario_id"], e["platform"]): e["result"] for e in matrix["entries"]}
    acceptance = load_json(root / "acceptance.json")
    for scenario in acceptance["mandatory_scenarios"]:
        lines.append(f"{scenario} | {by_key[(scenario, 'ANDROID')]} | {by_key[(scenario, 'IOS')]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate", "summary", "scope"])
    parser.add_argument("--root", default="docs/certification/core004")
    parser.add_argument("--progress", default="docs/DEVELOPMENT_PROGRESS.md")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    try:
        root = Path(args.root)
        if args.command == "validate":
            counts = validate_root(root, Path(args.progress))
            print("CORE-004 certification contract PASS")
            print(" ".join(f"{key}={counts[key]}" for key in sorted(counts)))
        elif args.command == "summary":
            print(summary(root))
        else:
            acceptance = load_json(root / "acceptance.json")
            changed = validate_scope(Path(args.repo_root), acceptance["base_sha"])
            print("CORE-004 scope guard PASS")
            for path in changed:
                print(path)
    except (ValidationError, subprocess.CalledProcessError) as exc:
        print(f"CORE-004 certification validation FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
