# CORE-004 — Passive Recording Real-device Certification V1

Issue: #190  
Base lock: `b8d5a01c8b2329bdadd9ea63df59bc705d834add`  
Branch: `test/core-passive-recording-real-device-certification-v1-20261002`

This directory is the durable evidence authority for the CORE-004 P0 release gate.

## Non-negotiable boundary

CORE-004 is a **real-device certification**, not a simulated test task.

CI, unit tests, mocked clocks, emulators and simulators may validate the harness or diagnose failures, but they **cannot turn any physical-device scenario PASS**. A matrix row may become `PASS` only when a matching real-device evidence JSON exists under `evidence/` and the observed field behavior satisfies the frozen V1 acceptance contract.

If a product defect is found, preserve the failing evidence, fix it in a separate narrow issue/PR, build a new exact HEAD, and rerun the affected scenario from the beginning.

## Mandatory matrix

Both Android and iOS require:

- C1 — 24h UI-independent passive recording
- C2 — 72h continuity + battery
- C3 — offline 12h durable replay
- C4 — platform-realistic process termination recovery
- C5 — device reboot recovery
- C6 — Privacy Pause
- C7 — permission / location-services disruption
- C8 — structured historical whereabouts query, provider calls = 0
- C9 — broad day question, evidence first
- C10 — Recording Health truthfulness
- OWNER_SESSION — owner/session isolation

`matrix.json` is the only machine-readable result matrix. Initial rows are intentionally `BLOCKED / PHYSICAL_RUN_NOT_EXECUTED`; that is truthful, not a failure of the harness.

Allowed result values are only:

`PASS`, `FAIL`, `BLOCKED`, `NOT_APPLICABLE`

`NOT_APPLICABLE` requires an explicit platform-specific justification.

## Frozen V1 thresholds

`acceptance.json` is frozen before field execution. In particular:

- C1 observation: at least 24h.
- C2 observation: at least 72h.
- C3 offline duration: at least 12h.
- unexplained recording loss while platform/auth/privacy authority is healthy: `>= 2h` fails C2.
- there is **no universal battery percentage threshold**.
- battery PASS still requires OS battery evidence and fails on observed runaway drain, thermal/continuous location abuse contrary to platform policy, or behavior that makes normal use impractical.

Changing the acceptance threshold after seeing a field result is not allowed. A threshold change requires explicit review and rerun.

## Creating evidence

1. Copy `templates/run-evidence.json` to `evidence/<unique-run-id>.json`.
2. Use a purpose-built field-test account and synthetic labels where practical.
3. Set the exact app `git_head`, build/version, installation source, device model, OS, timezone and real start/end times.
4. Attach privacy-safe screenshots/log extracts under `evidence/` as needed.
5. Put the evidence path into the matching `matrix.json` entry.
6. Set the matrix/evidence result to `PASS`, `FAIL`, `BLOCKED`, or justified `NOT_APPLICABLE`.
7. Run:

```bash
python scripts/core004_certification.py validate
python scripts/core004_certification.py summary
python scripts/test_core004_certification.py
```

The validator deliberately rejects a `PASS` row with no preserved evidence.

## Evidence integrity

Do not overwrite a failed run with a later passing run. Keep both files and point the matrix to the current certification evidence while retaining the old failed evidence for review.

Each evidence file must record:

- scenario ID and unique run ID
- exact Git HEAD/build
- real device platform/model/OS
- local and UTC start/end
- preconditions/actions/expected/observed
- Recording Health snapshots
- DayFootprint/Visit evidence
- queue/backlog evidence where relevant
- battery evidence where relevant
- attachments/paths
- scenario-specific machine checks
- final result

C2 PASS additionally requires Visit/Place quality observations to be documented. C10 must account for all six Recording Health states with either evidence or an explicit reason a state was not safely/reproducibly observed.

## Privacy rules

Never commit:

- precise latitude/longitude
- access/refresh tokens, Authorization headers, passwords or secrets
- IMEI, serial number, advertising ID or durable device identifier
- personal email
- personal Memory/photo/voice content

Redact home/work coordinates and identifying screenshots before commit. Prefer synthetic Place names.

The CI guard scans structured evidence keys and common credential/email patterns, but human privacy review is still required before formal certification review.

## Progress truth

While any mandatory row is `FAIL` or `BLOCKED`:

`CORE-004 🔵`

Only after all mandatory real-device evidence is complete:

`CORE-004 🟠`

Only after formal certification review + merge:

`CORE-004 ✅`
