#!/usr/bin/env python3
from pathlib import Path
import re
import sys

EXPECTED_VERSION = "1.1.1"
EXPECTED_SHA256 = "54dff0f39a5e48f0f668512bdba38a36dbcb63386db94491c6054f45cf435758"

root = Path(__file__).resolve().parents[1]
pubspec = (root / "pubspec.yaml").read_text(encoding="utf-8")
lock = (root / "pubspec.lock").read_text(encoding="utf-8")

dependency = re.search(
    r"(?m)^\s{2}csp_amap_flutter_map:\s*([^\n#]+?)\s*$",
    pubspec,
)
if dependency is None or dependency.group(1).strip() != EXPECTED_VERSION:
    raise SystemExit(
        "AMap bridge must stay exact-pinned to "
        f"csp_amap_flutter_map {EXPECTED_VERSION}; supply-chain re-review required."
    )

block = re.search(
    r"(?ms)^  csp_amap_flutter_map:\n(?P<body>(?:    .*\n)+)",
    lock,
)
if block is None:
    raise SystemExit("csp_amap_flutter_map missing from pubspec.lock")

body = block.group("body")
required = (
    f'version: "{EXPECTED_VERSION}"',
    f'sha256: "{EXPECTED_SHA256}"',
    'url: "https://pub.dev"',
    'source: hosted',
)
missing = [item for item in required if item not in body]
if missing:
    raise SystemExit(
        "AMap bridge lock provenance drifted; supply-chain re-review required: "
        + ", ".join(missing)
    )

for forbidden in ("git:", "path:", "^1.1.1", "any"):
    if re.search(
        rf"(?ms)^  csp_amap_flutter_map:.*?{re.escape(forbidden)}",
        pubspec,
    ):
        raise SystemExit(
            f"AMap bridge uses forbidden dependency form {forbidden!r}; "
            "supply-chain re-review required."
        )

print(
    "AMap bridge pin OK: "
    f"csp_amap_flutter_map {EXPECTED_VERSION} sha256={EXPECTED_SHA256}"
)
