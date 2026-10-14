# AUTH-005 Identity Linking, Unlinking, and Conflict Safety

## Status

CODE + Mock. The provider-neutral server contract and PostgreSQL authority are
implemented on the AUTH-005 branch. Real SMS/WeChat provider activation,
credentials, migration of existing user data, UI, and field acceptance are out
of scope. `AUTH_IDENTITY_LINK_PROVIDER=disabled` is the production-safe default.

## Authority

`User.id` remains the canonical account. `AuthIdentity(provider, subject)` is
the only login-identity authority. `User.email` and `User.phone` remain
projections; they are never used to infer ownership during linking.

The link request contains only an opaque provider credential, a separate opaque
recent-reauth credential, and a client request ID. The client cannot submit a
provider, phone, email, openid, unionid, or verified timestamp as authority. A
provider-neutral adapter returns the canonical subject only after verification.

## Link

`POST /v1/auth/identities/link` requires the current durable JiYi session and a
recent step-up proof. Provider verification is performed outside the database
identity critical section. The short transaction then:

1. locks the current User and rejects disabled or deleting accounts;
2. canonicalizes the server-produced subject;
3. locks the provider/subject identity key and rejects a different owner;
4. links the identity without creating, merging, or transferring a User;
5. fences every other active session for that User; and
6. commits one durable `AuthIdentityOperation` receipt.

The unique `(provider, subject)` constraint is the final multi-worker race
authority. A conflict is a generic HTTP 409 (`AUTH_IDENTITY_CONFLICT`); no
account existence or other owner data is disclosed.

## Unlink

`DELETE /v1/auth/identities/{identity_id}` uses the same current-session and
recent step-up contract. The User and identity rows are locked together. The
last remaining usable login identity cannot be removed. Usability includes the
current provider capability and, for email/password, a verified password
identity. Email/phone projections are recomputed from the remaining identity,
and other sessions are fenced only after the unlink is part of the same
successful transaction.

Disabled accounts and accounts in active deletion are hard-denied. There is no
automatic merge, ownership transfer, projection fallback, or user-data
migration. Future WeChat identities use the same provider-neutral path and
remain disabled until separately activated.

## Replay and audit

Every mutation request reserves a durable, unique request ID before provider
I/O. A same request ID with the same request fingerprint is deterministic; a
different payload is `AUTH_IDENTITY_OPERATION_CONFLICT`; an in-progress request
cannot be executed twice. Provider exceptions are recorded as terminal
`AUTH_IDENTITY_OPERATION_UNKNOWN`; stale `RESERVED` receipts are closed to the
same outcome after the configured reservation timeout. Neither path retries a
possibly consumed one-time credential.

Only HMAC fingerprints, provider request IDs, normalized outcome codes, and
non-sensitive timestamps are stored. Raw credentials, raw subjects and
step-up material are never persisted or logged. The dedicated fingerprint key
is server-only. Fake providers are selectable only outside production and are
used for deterministic tests; production silently falls back to disabled, not
to fake.

## API surface

- `GET /v1/auth/identities` returns only the current account's provider and a
  masked subject hint.
- `POST /v1/auth/identities/link` links a provider-verified identity.
- `DELETE /v1/auth/identities/{identity_id}` removes a non-last identity after
  step-up verification.

Both mutation routes consume the durable server-side IP rate-limit bucket
`identity_mutation_ip` before provider verification. The configured
`AUTH_IDENTITY_LINK_IP_LIMIT` and window apply across workers; disabling the
general auth limiter is the only way to disable this gate and is not permitted
by production configuration validation.

Stable errors include `AUTH_REAUTH_REQUIRED`, `AUTH_PROVIDER_UNAVAILABLE`,
`AUTH_PROVIDER_TOKEN_INVALID`, `AUTH_PROVIDER_SCOPE_MISMATCH`,
`AUTH_IDENTITY_CONFLICT`, `AUTH_IDENTITY_OPERATION_CONFLICT`,
`AUTH_IDENTITY_OPERATION_IN_PROGRESS`, `AUTH_IDENTITY_OPERATION_UNKNOWN`,
`AUTH_LAST_IDENTITY_REQUIRED`,
`AUTH_ACCOUNT_UNAVAILABLE`, and `ACCOUNT_DELETION_IN_PROGRESS`.

## Verification

The CODE + Mock suite covers production fake-provider fail-closed behavior,
same-request idempotency and provider single-call behavior, cross-owner
conflicts without transfer/merge, last-identity protection, masked listing,
session fencing, and real PostgreSQL identity-operation races. No live provider
endpoint or credential is used.
