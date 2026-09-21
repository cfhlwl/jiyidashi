# pgvector Foundation

Issue #66 / S3-008 adds PostgreSQL vector capability as infrastructure only.

## Ownership

This line owns:

- the bounded Python `pgvector>=0.5,<0.6` dependency;
- PostgreSQL `vector` extension enablement through Alembic revision
  `0012_pgvector_foundation`;
- a small SQLAlchemy `VECTOR` integration seam for later Stage 3 models;
- capability checks and PostgreSQL migration/downgrade CI;
- a pgvector-enabled PostgreSQL 16 development/CI image.

It does **not** own an embedding model, embedding dimensions, vector columns, user vector rows,
approximate indexes, nearest-neighbor queries, semantic-search APIs, or RAG.

## Migration contract

On PostgreSQL, upgrade executes:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

The database image/host must already provide the extension binaries and the migration role must
be allowed to enable the extension. If that is not true, migration fails closed with a clear
`PGVECTOR_EXTENSION_ENABLE_FAILED` boundary instead of silently degrading.

On SQLite, revision 0012 is intentionally a no-op. Existing non-vector development and unit-test
paths continue to work.

Other SQL dialects are not part of the supported vector capability and fail explicitly.

## Conservative downgrade

Downgrade intentionally does **not** execute:

```sql
DROP EXTENSION vector;
```

The extension is database-level shared state and may be used by another schema or service.
Rolling this application's Alembic revision back does not imply ownership to delete shared
database capability. Re-upgrade is idempotent through `CREATE EXTENSION IF NOT EXISTS`.

## No user-data migration

Revision 0012 creates no table, column, index, trigger, or user-owned row. In particular it does
not rewrite `Memory`, `MemorySource`, Evidence, Object, Place, Visit, or Reminder data.

The PostgreSQL CI gate seeds an existing Memory/Evidence pair, downgrades to 0011, re-upgrades
to head, and proves the core schema/data are unchanged while the vector extension remains
available.

Unit tests also assert that current ORM metadata contains zero `VECTOR` columns. Any user-owned
embedding storage therefore requires a later explicit S3-009 model + migration review.

## Runtime seam

`app.vector_support` exposes:

- `vector_type(dimensions=None)` for a future SQLAlchemy model;
- `inspect_vector_capability(connection)` to distinguish:
  - PostgreSQL with vector enabled;
  - SQLite, where vector is intentionally unavailable;
  - unsupported/misconfigured databases, which fail clearly.

No default dimension is chosen here. Embedding model and dimension policy belong to S3-009.

## S3-009 handoff

S3-009 may consume this foundation only after separately defining and reviewing:

- embedding provider/model policy;
- exact dimensions and model-version provenance;
- user-owned storage/deletion lifecycle;
- backfill/idempotency behavior;
- vector index lifecycle;
- retrieval trust boundaries.

S3-008 itself performs no embedding generation or retrieval.
