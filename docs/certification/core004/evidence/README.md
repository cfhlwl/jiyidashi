# CORE-004 evidence directory

Real field-run artifacts live here.

- JSON records must use `../templates/run-evidence.json`.
- The JSON filename must equal `run_id` exactly.
- Failed runs are immutable evidence and must not be deleted when a later rerun passes.
- Screenshots/log extracts must be redacted before commit.
- Never place tokens, precise coordinates, email addresses, device serial/IMEI/ad IDs, or personal Memory/photo/voice content here.

The certification validator scans this directory and rejects orphan JSON evidence that is not referenced by `../matrix.json`.
