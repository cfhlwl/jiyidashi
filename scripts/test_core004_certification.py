#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("core004_certification.py")
SPEC = importlib.util.spec_from_file_location("core004_certification", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)

BASE = Path(__file__).resolve().parents[1] / "docs" / "certification" / "core004"


class Core004CertificationTests(unittest.TestCase):
    def copy_contract(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="core004-"))
        target = tmp / "docs" / "certification" / "core004"
        target.mkdir(parents=True)
        for name in ("acceptance.json", "matrix.json"):
            (target / name).write_text((BASE / name).read_text(encoding="utf-8"), encoding="utf-8")
        progress = tmp / "docs" / "DEVELOPMENT_PROGRESS.md"
        progress.parent.mkdir(parents=True, exist_ok=True)
        progress.write_text(
            "| CORE-004 | P0 Gate | Passive Recording Real-device Certification V1 | 🔵 | active |\n",
            encoding="utf-8",
        )
        return tmp

    def test_initial_contract_is_active_and_blocked(self) -> None:
        counts = mod.validate_root(
            BASE,
            Path(__file__).resolve().parents[1] / "docs" / "DEVELOPMENT_PROGRESS.md",
        )
        self.assertEqual(counts["BLOCKED"], 22)
        self.assertEqual(counts["PASS"], 0)
        self.assertEqual(counts["FAIL"], 0)

    def test_missing_matrix_entry_fails(self) -> None:
        tmp = self.copy_contract()
        root = tmp / "docs" / "certification" / "core004"
        matrix = json.loads((root / "matrix.json").read_text(encoding="utf-8"))
        matrix["entries"].pop()
        (root / "matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
        with self.assertRaises(mod.ValidationError):
            mod.validate_root(root, tmp / "docs" / "DEVELOPMENT_PROGRESS.md")

    def test_progress_cannot_turn_orange_while_blocked(self) -> None:
        tmp = self.copy_contract()
        progress = tmp / "docs" / "DEVELOPMENT_PROGRESS.md"
        progress.write_text(
            "| CORE-004 | P0 Gate | Passive Recording Real-device Certification V1 | 🟠 | premature |\n",
            encoding="utf-8",
        )
        with self.assertRaises(mod.ValidationError):
            mod.validate_root(tmp / "docs" / "certification" / "core004", progress)

    def test_pass_requires_real_evidence(self) -> None:
        tmp = self.copy_contract()
        root = tmp / "docs" / "certification" / "core004"
        matrix = json.loads((root / "matrix.json").read_text(encoding="utf-8"))
        target = next(
            e for e in matrix["entries"]
            if e["scenario_id"] == "C1" and e["platform"] == "ANDROID"
        )
        target["result"] = "PASS"
        target["evidence"] = []
        target.pop("blocker_code", None)
        target.pop("blocker", None)
        (root / "matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
        with self.assertRaisesRegex(mod.ValidationError, "requires preserved evidence"):
            mod.validate_root(root, tmp / "docs" / "DEVELOPMENT_PROGRESS.md")

    def test_privacy_guard_rejects_sensitive_keys(self) -> None:
        data = {"device": {"serial": "should-never-be-committed"}}
        with self.assertRaisesRegex(mod.ValidationError, "forbidden privacy key"):
            mod.privacy_guard_json(data, {"serial"}, Path("evidence.json"))


    def test_privacy_guard_rejects_email_string(self) -> None:
        data = {"notes": "contact field-test@example.com"}
        with self.assertRaisesRegex(mod.ValidationError, "email-like value"):
            mod.privacy_guard_json(data, set(), Path("evidence.json"))


if __name__ == "__main__":
    unittest.main()
