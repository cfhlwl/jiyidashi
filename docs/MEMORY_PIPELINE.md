# Memory Pipeline Foundation

Issue #57 / S3-002 establishes the trusted orchestration boundary for future memory AI work.

## Pipeline

\`\`\`text
Capture
  -> Normalize
  -> Extract
  -> Classify
  -> Evidence decision
  -> Store decision
\`\`\`

The foundation intentionally does not implement real entity semantics. Extraction and
classification are injected stage adapters so later Entity work can plug in without
rewriting Evidence, owner or idempotency rules.

## Trust rules

- No eligible Evidence means no Memory persistence.
- AI-only Evidence is not eligible.
- Evidence below the existing 0.60 query threshold is not eligible.
- Stage output always remains \`trust_class=inference\`; adapters cannot promote it to
  a confirmed fact.
- A persisted candidate is stored as \`Memory.source_type=AI_INFERENCE\` and
  \`is_confirmed=false\`.
- Original Evidence is preserved separately in \`MemorySource\`; normalization never
  overwrites the source text.
- Existing query gates therefore continue to refuse inferred candidates until a future,
  explicit confirmation flow is designed.
- Expected stage failures fail closed. The orchestrator never fabricates fallback facts.

## Replay / idempotency

Persistence reuses the existing \`ClientMutation\` ledger with operation
\`MEMORY_PIPELINE_STORE_V1\`.

The same \`user_id + execution_id + fingerprint\` returns the existing Memory.
Reusing the same execution ID with a changed capture/candidate/evidence fails closed.
The same execution ID remains isolated between different owners.

## AI boundary

This foundation performs no model call itself. Any future AI-backed Normalize/Extract/
Classify adapter must depend on the merged \`AIGateway\`; provider SDKs, provider API
keys and direct model HTTP calls do not belong in pipeline stages.

## Out of scope

- concrete Person/Object/Place/Event extraction rules
- Entity Link or automatic entity creation
- embeddings / pgvector / RAG
- Reminder intent
- public Memory Pipeline API
