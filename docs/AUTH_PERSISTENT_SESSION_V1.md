# AUTH-001 — Public Auth & Persistent Session Hardening V1

## Scope

AUTH-001 replaces the former long-lived access-token-only public authentication model
with durable server session authority suitable for persistent background capture.

The public authentication chain is:

```
register
→ verify email
→ create durable session
→ short-lived access JWT
→ rotating opaque refresh token
→ server-authoritative cold-start restore
```

## Durable session authority

Access JWTs are short lived and include:

- issuer;
- audience;
- user subject;
- unique JWT id;
- durable session id;
- issued-at and expiry.

Every authenticated API request validates both the JWT and the current
`auth_sessions` row. Revoking a durable session therefore invalidates an otherwise
unexpired JWT.

Raw refresh tokens are never stored in the database. The server stores only a keyed
SHA-256 digest derived with the JWT secret.

Successful refresh rotation:

```
current refresh digest
→ row lock
→ consumed digest receipt
→ new opaque refresh token
→ new refresh digest
→ rotation revision + 1
→ new short-lived access JWT
```

A consumed refresh token presented again is replay. Replay revokes the affected durable
session and emits the existing security-alert signal path.

## Logout and revocation

The public API exposes:

- current-session logout;
- logout all sessions;
- active session listing;
- owner-scoped session revoke.

Password reset and password change revoke active sessions. Account deletion gates revoke
active public sessions before destructive work proceeds.

## Email verification

New email/password accounts do not receive authenticated owner authority at registration.
A single-use verification token is delivered through the configured email provider.

Only keyed token digests are stored. Existing accounts migrated into AUTH-001 remain
verified so production users are not silently locked out by the migration.

Production requires SMTP delivery configuration and an HTTPS public authentication base
URL. CI validates configuration without contacting the external SMTP host.

## Password recovery

Forgot-password is enumeration-safe: existing and missing accounts return the same public
accepted response.

Reset tokens are:

- random and opaque;
- stored only as keyed digests;
- single use;
- expiry bounded;
- rate limited.

Successful reset changes the password and revokes all durable sessions in the same
transaction.

## Flutter persistence

Flutter stores only:

- rotating refresh token;
- durable session id;
- installation id.

The secure store does not persist user id, password, or access JWT.

`flutter_secure_storage` backs this state with platform secure storage. Android is
pinned to API 24+ and app-data backup is disabled so secure credential blobs are not
silently migrated between devices.

Cold start never trusts local owner identity:

```
read secure refresh/session
→ call server /auth/refresh
→ validate same durable session id
→ rotate refresh token
→ publish server-returned user id/access JWT
→ enter owner UI
```

Invalid/replayed credentials clear local secure session state. Network-unavailable restore
keeps the refresh material for retry but does not publish authenticated owner authority.

Within one durable session, access JWT rotation does not change Flutter
`sessionVersion`. Actual logout/account switch does, preserving existing stale-response
and destructive-operation race protection.

## CORE-001 seam

Background work must not infer authority from persisted user ids or local app state.
The mobile client exposes a server-round-trip revalidation seam before owner-bound
background work is published. CORE-001 may consume this seam without inventing a second
authentication model.

## Required gates

AUTH-001 is not ready until exact-head CI proves:

- migration upgrade/downgrade and schema drift;
- JWT issuer/audience/session binding;
- refresh rotation and replay revocation;
- real PostgreSQL concurrent refresh exactly-one-success;
- revoked access JWT denial;
- logout/logout-all/session revoke;
- email verification single-use behavior;
- forgot/reset enumeration and session revocation;
- Flutter secure-store field boundary;
- cold-start server-authoritative restore;
- Android and iOS builds/tests;
- committed dependency lock;
- production deployment safety contract.
