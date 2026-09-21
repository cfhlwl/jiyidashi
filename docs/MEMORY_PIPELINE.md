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

Extraction and classification remain injected stage adapters. Issue #61 adds a small
Entity adapter that reuses the merged Entity Extraction + Link service without rewriting
Evidence, owner or idempotency rules.

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

## Entity adapter boundary

The Entity integration receives a typed \`MemoryPipelineExecutionContext\` created by the
orchestrator from the already-validated capture. \`user_id\` and \`execution_id\` are not
read from model output or free-form metadata. The adapter calls the merged
\`extract_and_link_entities(...)\` service and attaches its validated \`EntityLinkResult\`
objects as \`trust_class=inference\` internal annotations. Linked Object/Place IDs therefore
remain owner-scoped references, not Evidence and not confirmation of the Memory candidate.
Unresolved/ambiguous/cross-owner results remain unresolved.

Entity annotations do not participate in the Evidence decision and are not a bypass into
Store. \`NO EVIDENCE -> NO MEMORY\` and Store anti-bypass checks remain unchanged.

## AI boundary

The pipeline core performs no model call itself. AI-backed stage adapters must depend on
the merged \`AIGateway\`; provider SDKs, provider API keys and direct model HTTP calls do
not belong in pipeline stages. Entity extraction follows the same boundary through the
existing Entity service.

## Out of scope

- automatic entity creation or Person persistence
- fuzzy/AI entity linking
- embeddings / pgvector / RAG
- Reminder intent
- public Memory Pipeline API
