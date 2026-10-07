# AUTH-01 Canonical Identity Foundation

Status: audit and specification only. This document does not authorize provider SDK integration, database migration, API implementation, or UI changes.

Audit branch: `codex/auth-canonical-identity-v1-20261007`

Audit base: `origin/main` at `d67a3a510014fe66afc799fbc83bdbb6685b3b89`

Scope: canonical user identity, provider resolution, identity linking, session authority, deletion fencing, migration preflight, and future API/test boundaries.

## 1. Audit Boundary and Evidence

The audit was performed against the fetched `origin/main` base above. The following existing symbols are the primary evidence:

| Area | Actual file | Symbols / facts used by this specification |
|---|---|---|
| Durable user owner | `backend/app/models.py` | `User.id`, `User.phone`, `User.email`, `User.auth_disabled_at`; `User.id` is referenced by domain ownership foreign keys. |
| Identity model | `backend/app/auth_models.py` | `AuthProvider`, `AuthIdentity`, unique `(provider, subject)`, `AuthIdentity.user_id`, `secret_hash`, `verified_at`, `last_login_at`. |
| Email registration/login | `backend/app/services/auth_service.py` | `normalize_email`, `register_email_password`, `authenticate_email_password`, `lock_login_for_token_issue`. |
| Public session | `backend/app/services/auth_session_service.py` | `create_public_session`, `authenticate_access_session`, refresh rotation, session revoke operations. |
| JWT contract | `backend/app/core/security.py` | `AccessTokenClaims(user_id, session_id, jti, issued_at, expires_at)`, `create_access_token`, compatibility legacy session decoding. |
| Auth API | `backend/app/api/auth.py` | register, verify-email, login, refresh, logout, logout-all, password recovery/change, dev-token. |
| Profile boundary | `backend/app/api/users.py` | `GET /user`; `PATCH /user` changes profile fields only and explicitly excludes email/identity ownership. |
| Deletion boundary | `backend/app/services/account_deletion_service.py`, `backend/app/account_deletion_models.py` | durable deletion operation, user locking, identity deletion, final user deletion, session revocation. |
| Recovery | `backend/app/services/auth_recovery_service.py` | email identity lookup/locking, verification, password reset/change, session revocation. |
| Schema history | `backend/migrations/versions/0002_stage1_auth.py`, `0029_auth_persistent_session.py` | initial email identity, verified-at addition, persistent sessions, refresh receipts, one-time tokens, compatibility sessions. |
| Existing regression coverage | `backend/tests/test_stage1_auth.py`, `test_auth_persistent_session.py`, `test_account_delete.py`, PostgreSQL integration tests | current email/session/deletion behavior and concurrency assumptions. |

## 2. Current Authority Model

### 2.1 Durable ownership authority

`User.id` is the durable canonical owner identifier. It must remain stable across provider addition, email migration, phone migration, linking, unlinking, and any future account merge operation. Memories, Places, Family relationships, Media, Devices, Entitlements, usage, deletion operations, and sessions must continue to point to this same `User.id`.

No provider subject, email address, phone number, display name, or access-token claim may replace `User.id` as the owner key.

### 2.2 Authentication authority

The intended canonical authentication authority is `AuthIdentity`:

```text
(provider, canonical_subject) -> AuthIdentity.user_id -> User.id
```

The current database already enforces uniqueness of `(provider, subject)` in `AuthIdentity` and uses `AuthIdentity.user_id` for email-password login. However, the existing implementation is still email-only and registration also writes `User.email`. Therefore the current code is a partial implementation of the desired model, not proof that all provider paths already use it.

`User.email` and `User.phone` are profile/contact projections only. They are not independent login authorities. Existing operational reads may use them for display, search, export, or compatibility, but a new login or link flow must resolve through `AuthIdentity`.

### 2.3 Session authority

`AuthSession.user_id` is the server-side session owner. Modern `AccessTokenClaims` contains `user_id` and `session_id` plus token identifiers/timestamps. `create_public_session` validates the active user, persists the session and refresh digest, and issues a JWT bound to that durable session. Provider tokens must never become JiYi bearer credentials.

The current deletion behavior has two distinct authorities. `User.auth_disabled_at` is a hard deny for every provider and every session operation. An active `AccountDeletionOperation` is a deletion-continuation state: an already linked and successfully re-authenticated identity may obtain a continuation session for `/account/delete`, while ordinary user-data admission remains gated with 423. These states must not be collapsed into one boolean meaning.

The current pre-session compatibility JWT path in `backend/app/core/security.py` is migration-only. It must not be copied into new provider flows and must remain separately observable until its planned retirement.

## 3. Current Findings and Risks

1. `AuthIdentity(provider, subject)` is the actual email login lookup, but `User.email` is still `unique=True` and is written during registration. This creates two physical constraints and two possible sources of drift.
2. `User.phone` is unique and nullable, but current backend authentication code does not write it or resolve login from it. It must not be made authoritative by adding an ad hoc phone query.
3. `AuthProvider` currently contains only `EMAIL_PASSWORD`; provider expansion requires an explicit additive migration and a provider-neutral resolver.
4. `AuthIdentity` has no unique `(user_id, provider)` constraint, no explicit lifecycle status, no link timestamps, no provider scope/tenant field, and no separate immutable link audit record. The future policy must choose whether one user may have multiple identities of one provider before adding constraints.
5. `auth_service.register_email_password` already performs User, AuthIdentity, and default entitlement creation in one transaction and maps an `IntegrityError` to `AUTH_IDENTITY_EXISTS`. This is a useful concurrency pattern, but it is email-specific and should be generalized rather than duplicated.
6. `backend/app/api/users.py` explicitly prevents profile updates to email/identity ownership. That boundary must remain intact.
7. Admin projections, `UserRead`, and exports read `User.email`/`User.phone`; these consumers require a stable projection policy even after AuthIdentity becomes authoritative.
8. The dev-token endpoint can create a development User and issue a session without an AuthIdentity. This is an explicit development-only exception and must never be accepted by production provider resolution.
9. Account deletion explicitly removes `AuthIdentity` and deletes `User`; sessions, refresh receipts, and one-time tokens rely on foreign-key cascade. The deletion transaction and provider callback/new-user path must be tested as one lock/fencing boundary.
10. Current email recovery uses `AuthIdentity` and revokes sessions for password changes. Equivalent provider-neutral fencing is required for future link/unlink and provider credential changes.

## 4. Canonical Identity Decision

The AUTH-01 decision is:

- `User.id` is the canonical durable account/ownership key.
- `AuthIdentity` is the only canonical login identity authority.
- `(provider, canonical_subject)` is globally unique and maps to exactly one `User.id`.
- `User.email` and `User.phone` are contact/profile projections, not login lookup tables. AUTH-01 V1 permits at most one active `EMAIL_PASSWORD` identity and at most one active `PHONE` identity per User.
- Existing `User.id` values are never changed by migration, link, provider upgrade, or future merge preparation.
- A missing identity may create a new User only through the unified, concurrency-safe creation transaction.
- An identity already owned by another User fails closed. AUTH-01 never silently transfers, overwrites, or merges accounts.

This decision is compatible with current email login because `authenticate_email_password` already selects `AuthIdentity` by provider and normalized subject before loading the User. It is not compatible with adding a second provider-specific direct query against `User.email` or `User.phone`.

## 5. Provider Model

### 5.1 Planned provider identities

| Provider / method | Canonical identity namespace | Authority rule |
|---|---|---|
| `EMAIL_PASSWORD` | normalized email subject | Existing password identity; `secret_hash` is permitted only here. |
| `PHONE` | verified E.164 phone subject | The only permanent phone identity provider. One-tap and SMS are verification ceremonies, not provider identities. |
| `WECHAT` | scoped stable WeChat subject | Use the namespaced unionid/openid forms below; never use an unscoped value. |
| `APPLE` (future, not AUTH-01 implementation) | Apple stable `sub` scoped to the developer/client relationship | Do not use the relay email as the permanent subject. |

`EMAIL_PASSWORD` remains unchanged to avoid historical identity churn. `PHONE` is the permanent provider name. `PHONE_ONE_TAP` and `PHONE_SMS` are values for a verification-method/credential-ceremony field or audit event only. They must never create separate permanent identities. If product reporting needs to distinguish them, store `verification_method` as controlled metadata or an audit event; do not create two identities for one verified phone.

### 5.2 WeChat scope

The implementation specification must fix one exact serialization for the following logical namespaces:

```text
unionid:<scope>:<unionid>
openid:<app_id>:<openid>
```

`unionid` is preferred only when the configured applications are demonstrably in the same WeChat app group and the returned value is stable for this product. A bare `openid` is never globally portable between applications. AUTH-04 must re-check the then-current official WeChat scope rules before implementation; AUTH-01 records the required namespace shape without treating a third-party platform assumption as immutable.

An openid-to-unionid upgrade is an additive alias operation, not a subject mutation:

```text
existing: WECHAT + openid:<app_id>:O1 -> U1
verified result: WECHAT + unionid:<scope>:U123
transaction: create the unionid identity alias -> U1
```

The old openid identity remains valid for its scope unless a later provider policy explicitly retires it. The operation requires trusted provider verification and a lock on the existing identity/User. If the unionid already belongs to U2, fail closed with `AUTH_IDENTITY_CONFLICT`/`MERGE_REQUIRED`; never mutate the old subject and never auto-merge U1 and U2.

Provider app/tenant scope must be part of the subject or a separately constrained provider-scope column. A subject from a different application scope must fail with `AUTH_PROVIDER_SCOPE_MISMATCH` rather than collide.

## 6. Subject Canonicalization

Canonicalization occurs after provider credential verification and before identity lookup. Raw provider credentials are not subjects.

### Email

- Trim surrounding whitespace.
- Apply Unicode-aware `casefold()` consistent with the existing `normalize_email` behavior.
- Apply an explicit IDNA/local-part policy before production rollout; do not let framework display formatting decide equality.
- Reject malformed or ambiguous values rather than storing multiple representations.
- Store and query the canonical subject. The `User.email` projection is written from this canonical value according to the projection policy.

### Phone

- Parse with a maintained phone-number library and an explicit default region policy.
- Convert to E.164, including the leading `+`.
- Reject impossible, ambiguous, or unverified values.
- Use the verified E.164 value as the canonical phone subject, or an equivalent documented `phone:<E164>` namespace.
- Never use local formatting, masked phone text, carrier-returned display text, or an unverified request parameter as the subject.

### WeChat

- Use the scoped unionid/openid forms in Section 5.2.
- Treat the app scope as part of equality.
- Never use nickname, avatar URL, display name, session token, authorization code, access token, or temporary code as a permanent subject.

### General prohibition

No permanent identity may use a nickname, display name, masked phone, access token, refresh token, authorization code, SMS code, one-tap exchange token, provider temporary code, or mutable email display string as its subject.

## 7. User.email and User.phone Projection Policy

### Decision

`User.email` and `User.phone` remain compatibility/profile/contact projections. The identity repository/resolver is the sole authority for login and link ownership.

### Current read/write evidence

- `backend/app/services/auth_service.py` writes `User.email=subject` during email registration and reads `AuthIdentity` for login.
- `backend/app/api/users.py` returns `UserRead` but `PATCH /user` updates only nickname, timezone, locale, and elder mode; its comment explicitly says email/identity ownership is not changed through profile API.
- `backend/app/services/admin_projection_service.py` reads email for operational display/search and family detail.
- `backend/app/services/export_service.py` includes phone and email in export output.
- No current backend auth flow writes `User.phone`; its uniqueness is a schema constraint, not proof of phone-auth support.

### V1 cardinality and future rules

1. Only identity link, unlink, reconciliation, or migration code may update these projections, in the same transaction as the identity change.
2. A projection is selected from an explicitly verified, active primary contact identity. It is not selected from an arbitrary callback payload.
3. A phone-only or WeChat-only new User may have `User.email = NULL`. Existing email is not overwritten by a phone/WeChat link.
4. A verified phone identity projects E.164 into `User.phone`; unlink clears it only when no remaining active verified phone identity exists.
5. AUTH-01 V1 locks one active `EMAIL_PASSWORD` identity per User and one active `PHONE` identity per User. `WECHAT` is not subject to a global one-row-per-provider rule because future provider aliases, such as openid plus unionid, may be needed for the same User.
6. A link to an occupied email or phone identity fails closed with `AUTH_IDENTITY_ALREADY_LINKED`; it does not overwrite the projection or transfer ownership.
7. On email/phone link, update the corresponding single-value projection from the canonical identity in the same transaction. On unlink, clear that projection only if no active identity of that provider remains; V1 cardinality means the normal result is either the linked canonical value or NULL.
8. The invariant is both service-level and database-level: the service rejects a second active identity, and the schema phase must add an equivalent partial unique index or equivalent guard for `(user_id, provider=EMAIL_PASSWORD)` and `(user_id, provider=PHONE)`. Do not add a global `(user_id, provider)` uniqueness rule that would block future WeChat aliases.
9. Profile, admin, and import code must not directly mutate email/phone to obtain login authority.
10. Existing User rows and all domain foreign keys retain their `user_id`; projection reconciliation never creates a replacement User.

Supporting multiple email or phone identities is out of V1. It requires a dedicated contact/primary-identity model and an explicit admin/export policy; a single-value projection must never randomly choose among multiple identities.

## 8. Unified Login Resolution

Every provider adapter must end at one resolver with this contract:

```text
verify provider credential outside the resolver
canonical_subject = canonicalize(provider, verified provider result)
identity = load AuthIdentity(provider, canonical_subject) under the identity conflict lock
if identity exists:
    user = load identity.user_id under the User/deletion boundary
    issue_authenticated_session(user, device and client context)
else:
    create User + AuthIdentity + projections + defaults in Transaction A
    COMMIT
    issue_authenticated_session(new_user, device and client context)
return the same public session response shape
```

`resolve_verified_identity(...)` owns provider-neutral canonicalization, identity lookup/creation, duplicate handling, and idempotency. `issue_authenticated_session(...)` is the shared issuance authority: it locks the canonical User, hard-denies `auth_disabled_at`, inspects `AccountDeletionOperation`, determines normal versus deletion-continuation mode, calls `create_public_session`, and returns tokens plus `account_deletion_in_progress`. Provider adapters must not each implement their own User lookup, merge behavior, session JWT, deletion check, continuation flag, or logout semantics.

`create_public_session` remains the reusable session boundary. Provider access tokens are verification inputs only and are never persisted in `AuthIdentity` or accepted as JiYi API bearer tokens.

## 9. New User Creation and Concurrency

New-user creation is Transaction A:

1. Validate and canonicalize the verified subject.
2. Lock or atomically claim the `(provider, subject)` unique key.
3. Re-read an existing identity after an integrity conflict.
4. If absent, create the User, AuthIdentity, projection values, and default entitlement together.
5. Commit once. Session issuance is a separate boundary owned by `issue_authenticated_session(...)` and `create_public_session(...)`.

Two concurrent first logins for the same canonical phone or WeChat subject must produce one identity and one User. The losing transaction must roll back its provisional User and either return the same idempotent result or report that the identity is now owned by the winning User. It must never create a second User, change `user_id`, or perform a silent merge.

If Transaction A commits but session issuance fails, a provider retry resolves the already committed AuthIdentity to the same User.id and retries issuance. It must not create a second User or identity. The idempotency record/request ID must make a repeated successful request return the same logical outcome without duplicate side effects.

For a known identity, a concurrent deletion or disable operation must win according to the User-row/deletion lock ordering. A callback must re-check the identity and User after acquiring the lock.

## 10. Identity Linking, Unlinking, and Re-authentication

AUTH-01 defines the security boundary; endpoint implementation is later.

### Link transaction

- Require an authenticated current User and recent re-authentication/step-up appropriate to the provider risk.
- Verify the provider credential first; never accept a raw authorization code or unverified phone string as proof.
- Canonicalize the subject.
- Lock the current User and the identity conflict key in a stable order.
- Reject hard-disabled accounts; for an active deletion operation, use the shared continuation policy in Section 13.
- Create the identity only if absent, update the contact projection only according to Section 7, and record an immutable audit event.
- Accept an idempotency key/request ID; retries return the same result without creating another identity or changing ownership.

### Unlink transaction

- Require re-authentication/step-up.
- Lock User and identity.
- Refuse removal of the last active login method unless a replacement method is verified in the same controlled transaction or product policy explicitly supports a recovery state.
- Recompute contact projections from remaining active verified identities.
- Apply the agreed session fence/revocation policy and record the event.

Link/unlink must not be exposed through the profile API. Session revocation policy is an open product decision for normal links, but password/phone security changes must at least support immediate fencing of affected sessions.

## 11. Identity Conflict and Merge Boundary

If U1 attempts to link a canonical identity currently owned by U2:

- fail closed with HTTP 409 and `AUTH_IDENTITY_ALREADY_LINKED` (or the more general `AUTH_IDENTITY_CONFLICT`);
- record an audit event without secrets;
- do not transfer the identity, overwrite a projection, create a duplicate, or merge accounts;
- return `MERGE_REQUIRED` only as an explicit future-flow signal, never as permission to merge in AUTH-01.

Account merge belongs to AUTH-05. Its preconditions must include re-authentication of both accounts, explicit user confirmation, and an ownership migration plan for:

- Memories, Places, Family membership/permissions, Media and external objects;
- Entitlements, billing/receipts, quotas and usage;
- Devices, sessions, refresh-token families and security history;
- account deletion operations, data-deletion requests and recovery state.

Merge needs conflict rules, an auditable operation record, rollback or resumable saga behavior, and a final identity ownership check. No automatic merge is part of this specification.

## 12. Session and Token Authority

The current session design is retained:

- `AuthSession.user_id` is the server-side source of session ownership.
- Access claims contain `user_id`, `session_id`, `jti`, `iat`, and `exp`; they do not contain provider access tokens or provider identity objects.
- Refresh tokens are random bearer secrets returned once; only digests/receipts are persisted.
- `authenticate_access_session` validates the durable session, revocation/expiry, User existence, and `auth_disabled_at`.
- `EMAIL`, `PHONE`, `WECHAT`, and email-verification completion all converge to the provider-neutral `issue_authenticated_session(...)` boundary, which then calls `create_public_session`.
- The shared issuance boundary applies the same User lock ordering, `auth_disabled_at` hard deny, `AccountDeletionOperation` continuation decision, and `account_deletion_in_progress` response flag for every provider.
- Password change, reset, logout, logout-all, deletion, and security-sensitive link/unlink actions must use the same session fencing primitives.

Provider tokens and temporary credentials are transient verification inputs. If a future provider needs a refresh token for an explicit product feature, it requires a separate encrypted secret store with rotation, scope, retention, and revocation policy; `AuthIdentity` is not that store.

## 13. Account Deletion and Auth-Disabled Boundaries

### A. `auth_disabled_at`: hard deny

`User.auth_disabled_at` is a global hard deny. For `EMAIL`, `PHONE`, and `WECHAT`, an account with this value set must not:

- create a new session;
- refresh an existing session;
- continue accessing authenticated APIs;
- link, unlink, verify, recover, or otherwise bypass the account fence.

All such paths use the existing `AUTH_ACCOUNT_UNAVAILABLE` semantic. AUTH-01 does not introduce a second public `AUTH_ACCOUNT_DISABLED` code unless a future client contract proves a distinct behavior is required.

### B. Active `AccountDeletionOperation`: continuation, not hard deny

An active `AccountDeletionOperation` is different from `auth_disabled_at`. Current formal email behavior is the authority for the provider-neutral design:

```text
existing linked identity successfully re-authenticated
    -> issue deletion-continuation session
    -> TokenResponse.account_deletion_in_progress = true
    -> ordinary user-data APIs remain gated with 423
    -> /account/delete continuation may proceed
```

The shared `issue_authenticated_session(...)` service must therefore:

- allow a known, linked, successfully re-authenticated identity to receive a continuation session;
- preserve `account_deletion_in_progress = true` in the token response;
- allow only the deletion continuation operation;
- deny ordinary user-data writes, ordinary user-data authority, new identity creation, identity linking, projection changes, and creation of a new canonical account;
- apply the same semantics to future PHONE and WECHAT paths.

An identity that does not exist cannot be guessed into a deleting account using `User.phone`, `User.email`, nickname, provider profile, or any other projection. If no canonical identity can be associated with a User, resolution follows the normal new-account path, with no automatic merge; the new account must still pass the normal deletion/disabled checks for its own User.

After final deletion, the expected state is that `User`, its `AuthIdentity` rows, and its `AuthSession` rows no longer exist; refresh receipts and one-time tokens must also be absent through verified foreign-key cascade or explicit deletion. If no permanent tombstone exists, AUTH-01 does not invent one: the policy is that the same provider subject may register a new User after deletion completes, subject to the normal uniqueness and verification rules. A future anti-reuse/tombstone policy would require an explicit additive design.

### C. Deletion transaction and race boundary

The current `account_deletion_service` explicitly deletes AuthIdentity and then User in the final transaction. AuthSession, AuthRefreshTokenReceipt, and AuthOneTimeToken have User/session foreign keys with cascade behavior in the current model/migrations. AUTH-01 requires a migration preflight to verify the live PostgreSQL constraints and a race test proving no usable session/identity survives final deletion. Provider callback/new-user creation must re-check the User/deletion boundary after acquiring the same lock; it must not recreate a deleted account from a subject alone.

## 14. Abuse Controls, Privacy, and Audit

### Abuse controls

The current email flow has IP/account gates, dummy Argon2 work for unknown identities, password verification, and refresh replay handling. Future provider flows must add, as applicable:

- per-IP, per-account, per-device, and global concurrency limits;
- OTP send, resend, verify, expiry, attempt, replay, and carrier-exchange limits;
- provider callback replay and nonce/state validation;
- WeChat/Apple provider error normalization and scope validation;
- alerting for identity-conflict storms, enumeration attempts, and repeated failed links.

### Privacy and logging

- Store only the minimum canonical subject, provider scope, verification status/timestamps, and lifecycle data needed for authorization.
- Treat phone/E.164, email, provider subject, and metadata as access-controlled personal data; decide encryption/tokenization and retention before migration.
- Never log raw passwords, SMS codes, one-tap exchange tokens, provider access/refresh tokens, authorization codes, or carrier tokens.
- Link/unlink/conflict audit events may contain user IDs, provider, a redacted or one-way subject fingerprint, request/correlation ID, result code, and timestamps; they must not contain raw credentials.
- Provider errors returned to clients must be stable JiYi failure codes, not raw vendor responses or subject data.

## 15. Migration Preflight and Non-Destructive Plan

No migration is executed by AUTH-01. The following queries/checks are required before any schema or backfill work. SQL syntax must be adapted to the actual database engine and verified on a read-only snapshot.

### Required preflight checks

1. Casefold/trimmed `User.email` duplicates:

   ```sql
   SELECT lower(trim(email)) AS canonical, count(*)
   FROM users
   WHERE email IS NOT NULL
   GROUP BY lower(trim(email))
   HAVING count(*) > 1;
   ```

2. Duplicate `(provider, normalized subject)` values in `auth_identities`.
3. Orphan `AuthIdentity` rows whose `user_id` has no User.
4. Users whose canonical email differs from their `EMAIL_PASSWORD` identity subject.
5. Users with more than one `EMAIL_PASSWORD` identity, and separately any more than one `PHONE` identity after phone canonicalization.
6. Unverified identities, identities with null/invalid `secret_hash`, and identities with missing timestamps.
7. Users created by historical/dev-token paths with no AuthIdentity.
8. Existing non-null `User.phone` inventory, format validity, duplicate canonical phone values, and source of each value.
9. Active `AccountDeletionOperation` rows, their User IDs, and whether each linked identity is still resolvable for continuation.
10. Users with `auth_disabled_at` set, including sessions and identity rows that must be rejected.
11. Sessions whose User no longer exists, plus orphan refresh receipts and one-time tokens; invalid/colliding compatibility sessions from `0029_auth_persistent_session.py`.
12. Any active provider callback/recovery jobs that could race with deletion or disable fencing.

### Additive schema plan

- `0002_stage1_auth.py` uses `sa.Enum(..., native_enum=False)`. Do not assume that adding Python enum members automatically requires a database enum migration. Before implementation, inspect actual PostgreSQL DDL, SQLite test schema, column length/check constraints, and the Alembic autogenerate diff.
- If the provider expansion is only a Python enum change with no database check/length/index/constraint change, the migration may be a documented schema no-op. If a schema/index/constraint/column changes, create and review the corresponding migration.
- Expand provider values additively; preserve `EMAIL_PASSWORD` compatibility and formally add `PHONE` rather than `PHONE_ONE_TAP`/`PHONE_SMS` identities.
- Add explicit identity lifecycle fields such as `status`, `linked_at`, `disabled_at`, and `updated_at`, and a constrained provider scope/tenant field if needed.
- Add partial unique indexes or equivalent database guards for active `(user_id, provider=EMAIL_PASSWORD)` and `(user_id, provider=PHONE)` only after preflight shows no violations. Do not add a global `(user_id, provider)` uniqueness rule, because WECHAT may need openid and unionid aliases for one User.
- Retain and strengthen the existing `(provider, subject)` uniqueness constraint.
- Add lookup indexes for `user_id, provider`, active status, and provider scope as required.
- Keep provider secrets out of the identity table; `secret_hash` remains a password hash field only.

### Email compatibility backfill

Backfill or reconcile email identities only after preflight. Preserve every `User.id`; never create replacement Users. A mismatch or duplicate is a manual/quarantined conflict, not an automatic merge. Compatibility verification status must be based on documented historical evidence, not guessed from a new provider callback.

Use staged dual-read/dual-write only during a controlled rollout: AuthIdentity is read authority, projections are maintained transactionally, and divergence is observable. Do not drop legacy columns or constraints until reconciliation, rollback, and client coverage are proven.

## 16. Future API Contract Plan

AUTH-01 defines boundaries, not implementation. Planned endpoints/services should be provider-neutral:

- `POST /auth/provider/resolve` or provider-specific adapters that terminate at one resolver;
- `GET /auth/identities` for the current User's redacted active identities;
- `POST /auth/identities/link` with provider verification result, re-auth/step-up, request ID/idempotency key;
- `DELETE /auth/identities/{identity_id}` with re-auth and last-identity protection;
- existing email register/login/recovery routes remain compatibility adapters over the same identity/session authority;
- provider verification callbacks use nonce/state, scope, replay, and idempotency checks before resolution.

Responses return JiYi user/session identifiers and stable failure codes. Vendor-specific token or error payloads never become the public API contract. API implementation is out of scope for this document.

## 17. Failure Codes

The following stable codes are reserved for the identity foundation:

| Code | Meaning |
|---|---|
| `AUTH_IDENTITY_EXISTS` | Compatibility duplicate during registration. |
| `AUTH_IDENTITY_ALREADY_LINKED` | Canonical identity is owned by another User. |
| `AUTH_IDENTITY_CONFLICT` | General identity ownership/normalization conflict. |
| `AUTH_IDENTITY_NOT_FOUND` | Requested identity does not exist or is not visible. |
| `AUTH_IDENTITY_UNVERIFIED` | Identity proof is not complete. |
| `AUTH_REAUTH_REQUIRED` | Recent authentication/step-up is required. |
| `AUTH_PROVIDER_UNAVAILABLE` | Provider could not complete verification. |
| `AUTH_PROVIDER_TOKEN_INVALID` | Provider credential failed verification. |
| `AUTH_PROVIDER_TOKEN_REPLAYED` | Provider credential/nonce was reused. |
| `AUTH_PROVIDER_SCOPE_MISMATCH` | Subject belongs to an unexpected app/tenant scope. |
| `AUTH_ACCOUNT_UNAVAILABLE` | `auth_disabled_at` hard deny; no new session, refresh, authenticated API access, link, or recovery bypass. |
| `ACCOUNT_DELETION_IN_PROGRESS` | Active deletion state exposed to ordinary data APIs/continuation-aware clients; a known linked identity may receive only a deletion-continuation session. |
| `AUTH_SESSION_INVALID` | Session is absent, expired, revoked, or no longer backed by a User. |
| `AUTH_LINK_IDEMPOTENCY_CONFLICT` | Same idempotency key was reused with different input. |
| `AUTH_LAST_IDENTITY_REQUIRED` | Unlink would leave no approved login method. |
| `MERGE_REQUIRED` | Explicit future merge flow is needed; no merge was performed. |
| `INVALID_CREDENTIALS` | Generic invalid email/password response. |

## 18. Test Matrix

These are design-time acceptance cases for future implementation; AUTH-01 does not add or run them.

| Scenario | Expected result |
|---|---|
| Existing email login | AuthIdentity resolves existing User; one normal public session; no new User. |
| New verified phone login | One User, one canonical phone identity, projection and default entitlement in one transaction. |
| New verified WeChat login | Scoped unionid/openid identity; no provider token persisted; one normal session. |
| Link phone/WeChat to email User | Step-up + provider verification; same User.id; transactional projection update. |
| U1 links phone already owned by U2 | 409 `AUTH_IDENTITY_ALREADY_LINKED`; no transfer/merge/overwrite. |
| Concurrent first login with same phone | Exactly one identity/User; losing transaction converges or returns conflict; no duplicate. |
| Concurrent first login with same WeChat subject | Same as phone, including scope collision protection. |
| Link retry with same idempotency key | Same result and identity; no duplicate audit/identity. |
| Reuse idempotency key with different subject | `AUTH_LINK_IDEMPOTENCY_CONFLICT`. |
| Linked identity vs active deletion | Email/Phone/WeChat re-authentication may issue only `account_deletion_in_progress=true` continuation session; ordinary data API remains 423. |
| Unknown subject vs active deletion | No projection or provider profile guessing; normal new-account resolution only, with no automatic merge. |
| Deletion vs final login/callback | User/deletion lock ordering prevents an unusable session or post-delete identity recreation. |
| Deletion vs link/callback | No new identity, link, projection change, or canonical account creation may attach to a deleting User. |
| `auth_disabled_at` for every provider | All resolution, link, callback, session issue, access, refresh, and recovery paths fail with `AUTH_ACCOUNT_UNAVAILABLE`. |
| Session after provider verification | Claims are only `user_id/session_id/jti/time`; provider token is not bearer or persisted in identity. |
| Unlink last login method | Rejected unless replacement is verified in the same guarded flow. |
| Existing email migration | Duplicate/mismatch preflight quarantines conflict; User.id and all domain ownership remain unchanged. |
| Projection consistency | Email/phone projections match selected active verified identities after link/unlink/reconciliation. |
| WeChat openid/unionid upgrade | Scope validated; no silent merge of existing Users. |
| Provider callback replay/disabled User | Stable replay/disabled failure; no side effect. |
| Refresh/logout/session fencing | Existing persistent-session rotation/replay/logout semantics remain intact for every provider. |
| Logging/privacy | No raw passwords, OTPs, provider tokens, or temporary codes in logs/audit. |

## 19. Final Decision Table

| Decision | AUTH-01 rule |
|---|---|
| Canonical User | `User.id` |
| Authentication authority | `AuthIdentity` |
| Email identity | `EMAIL_PASSWORD` + normalized email |
| Phone identity | `PHONE` + E.164 |
| Phone verification methods | `ONE_TAP` / `SMS`; methods only, not identities |
| WeChat | `WECHAT` + namespaced unionid/openid subject |
| Session authority | `AuthSession.user_id` |
| `User.email` / `User.phone` | Projection only; V1 cardinality is one active email identity and one active phone identity per User |
| Identity conflict | Fail closed with `AUTH_IDENTITY_ALREADY_LINKED`/`AUTH_IDENTITY_CONFLICT` |
| Automatic merge | No |
| Explicit merge | AUTH-05 only |
| `auth_disabled_at` | Hard deny with `AUTH_ACCOUNT_UNAVAILABLE` |
| Active account deletion | Known linked identity may receive deletion-continuation session only; ordinary user data remains gated |
| New User transaction | User + AuthIdentity + projection + default entitlement in Transaction A; session is separate |

## 20. Implementation Order (Future Work Only)

1. **Phase 0 — audit/preflight:** run read-only inventory, duplicate/orphan reports, scope decisions, and production rollback rehearsal.
2. **Phase 1 — additive foundation:** schema/provider values, lifecycle/scope fields, constraints/indexes, repository and unified resolver with no new third-party providers.
3. **Phase 2 — email compatibility:** reconcile existing email projections/identities, preserve current login/recovery behavior, add concurrency and projection tests.
4. **Phase 3 — link/unlink:** re-authentication, idempotency, audit, last-identity policy, session fencing, and API contract.
5. **Phase 4 — provider adapters:** `PHONE` verification ceremonies (one-tap/SMS) and WeChat in separate AUTH-02+ work, each with provider verification and scope/replay tests.
6. **AUTH-05 — explicit merge:** only after identity/link/deletion ownership invariants are proven.
7. **Rollout gates:** metrics, conflict quarantine, backfill verification, staged dual-read/write, rollback, and legacy compatibility sign-off.

No phase above is being implemented by AUTH-01.

## 21. Answers to the Twelve AUTH-01 Review Questions

1. **What is the canonical account owner?** `User.id`, unchanged for the lifetime of an account and across provider changes.
2. **What is the canonical login authority?** `AuthIdentity(provider, canonical_subject)` mapping to exactly one `User.id`.
3. **Are User.email and User.phone authorities?** No. They are controlled profile/contact projections with compatibility reads.
4. **Will phone one-tap and SMS create duplicate accounts?** No. Both are verification methods for `PHONE + E.164` and converge to one AuthIdentity/User.id.
5. **What is the permanent WeChat subject?** A fixed namespaced subject: `unionid:<scope>:<unionid>` or `openid:<app_id>:<openid>`; never a bare openid across apps.
6. **Can provider tokens or display data identify an account?** No. Tokens, codes, nicknames, display names, masked numbers, and mutable display values are prohibited as subjects.
7. **What happens when an identity belongs to another User?** Fail closed with `AUTH_IDENTITY_ALREADY_LINKED`/`AUTH_IDENTITY_CONFLICT`; no automatic merge.
8. **Where does account merge happen?** AUTH-05 only, after dual re-authentication, ownership migration, conflict policy, audit, and rollback design.
9. **How are new accounts made safely?** User, identity, projections, and defaults are created in Transaction A behind the provider-subject uniqueness constraint; session issuance is a separate retryable boundary.
10. **How are sessions issued?** Every provider and email-verification completion converges to `issue_authenticated_session(...)`, which applies hard-deny/continuation semantics and then calls `create_public_session`.
11. **What wins during disable/deletion races?** `auth_disabled_at` is a hard deny; active deletion permits only linked-identity continuation. Both use one User lock ordering and no provider bypass.
12. **What is AUTH-01 allowed to change now?** Only this specification document; no provider SDK, DB migration, backend code, mobile code, UI, native code, commit, or push.

## 22. Open Questions

These are the remaining product/operations decisions; they do not change the firm authority rules above:

- Should stored phone/email projections be encrypted/tokenized, and what are retention/deletion requirements?
- Which WeChat applications are in one unionid app group, and is the app scope stable across iOS, Android, and mini-program?
- What tenant/provider scope is required for all current and future clients?
- What exact replacement/last-identity policy is required for unlink?
- Which link/unlink operations revoke all sessions, only affected sessions, or require a session-generation fence?
- What are the live PostgreSQL version/DDL capabilities and zero-downtime requirements?
- How should admin search/export represent multiple future contact identities?
- When will the development-only identity-less `dev-token` path be removed or isolated from production configuration?
- What durable idempotency store is required for provider callbacks and link operations?

Firm decisions already made: User.id never changes; AuthIdentity is login authority; V1 permits one active EMAIL_PASSWORD and one active PHONE identity per User; projections are not authority; provider tokens are not bearer credentials; identity conflicts fail closed; AUTH-01 does not merge or implement providers.

## 23. Review Gate

AUTH-01 is ready for security/product review only after confirming the open questions, approving the additive migration plan, and assigning separate implementation work. Until then, the UI branch remains isolated and this branch must contain only this specification file.
