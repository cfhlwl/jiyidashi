#!/usr/bin/env python3
"""Verify every production pyproject dependency is frozen in the release lock."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "backend" / "pyproject.toml"
LOCK = ROOT / "backend" / "requirements.production.lock"


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dependency_name(spec: str) -> str:
    match = re.match(r"^([A-Za-z0-9_.-]+)", spec)
    if match is None:
        raise AssertionError(f"unsupported dependency spec: {spec!r}")
    return normalize(match.group(1))


def main() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    direct = {
        dependency_name(spec)
        for spec in project["project"]["dependencies"]
    }

    locked: dict[str, str] = {}
    for raw_line in LOCK.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, version = line.partition("==")
        assert sep and version and not any(
            token in version for token in ("<", ">", "~=", "*")
        ), f"lock entry must be exact: {line!r}"
        key = normalize(name)
        assert key not in locked, f"duplicate lock entry: {name}"
        locked[key] = version

    missing = sorted(direct - locked.keys())
    assert not missing, f"production lock missing direct dependencies: {missing}"
    assert "pytest" not in locked
    assert "pytest-asyncio" not in locked
    assert "ruff" not in locked

    print(
        "production dependency lock PASS: "
        f"{len(direct)} direct / {len(locked)} total pinned packages"
    )


if __name__ == "__main__":
    main()
