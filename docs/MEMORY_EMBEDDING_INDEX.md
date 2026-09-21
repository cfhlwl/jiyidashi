# Memory Embedding Index

Issue #69 / S3-009 adds a PostgreSQL-only derived vector index for authoritative Memory rows.

## Trust boundary

Embedding is search infrastructure, not Evidence, confirmation, confidence, or a MemorySource.

```text
authoritative owner-scoped Memory
-> server canonical text
-> SHA-256 fingerprint + edit revision
-> server-only embedding gateway
-> exact model/dimension/vector validation
-> re-lock/revalidate Memory
-> one current MemoryEmbedding row
```

No semantic-search API or answer generation is introduced here.

## Canonical input

The provider receives only:

```text
memory_type=<current Memory.memory_type>
title=<current title, when present>
content=<current content>
```

S3-009 deliberately excludes metadata_json, coordinates, object-storage keys, auth data,
raw unrelated Evidence payloads, and any other owner records.

## Reviewed policy

- provider: disabled by default; optional server-side OpenAI adapter
- model: `text-embedding-3-small`
- dimensions: `1536`
- distance/index policy: pgvector HNSW + `vector_cosine_ops`
- one current row: `memory_embeddings.memory_id` primary key
- database owner binding: `(memory_id, user_id) -> memories(id, user_id)`
- raw vectors: never exposed by a public API

Model and dimensions are configuration fields only so deployment can validate them; this
revision rejects values outside the reviewed policy.

## Refresh lifecycle

1. lock owner-scoped, non-deleted Memory;
2. build canonical text, fingerprint, revision snapshot;
3. return idempotently when the current row already matches fingerprint/model/dimension;
4. delete any stale current row and commit the short transaction;
5. perform provider I/O with no long-lived DB transaction;
6. require an exact 1536 finite numeric vector;
7. re-lock Memory and recompute the canonical fingerprint/revision;
8. fail closed if Memory changed;
9. serialize concurrent finalization through the Memory row lock;
10. write one current derived row and commit through GuardedSession.

A concurrent worker may waste provider I/O, but cannot create a duplicate current row.

## Invalidation and deletion

A title/content edit deletes the old embedding in the same trusted edit transaction.
Soft-delete deletes the embedding before the Memory deletion commit.

Data Delete explicitly counts/deletes owner embeddings before Memory rows. Account Delete
reuses that durable Data Delete lifecycle, and database foreign keys remain a final cascade
backstop.

SQLite remains a non-vector path. Migration 0013 is intentionally a SQLite no-op, and the
generation service fails closed before provider I/O when the database is not PostgreSQL.

Migration 0013 is historical/self-contained: it freezes `VECTOR(1536)` inside the migration
and imports only the versioned pgvector SQLAlchemy type, not mutable application policy/helper
modules. Future embedding policy changes therefore cannot rewrite the meaning of a fresh 0013
migration.
