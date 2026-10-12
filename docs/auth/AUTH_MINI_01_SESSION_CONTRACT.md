# AUTH-MINI-01 Mini Program Session Contract

## Status

`SECURITY REMEDIATION COMPLETE / INDEPENDENT REVIEW PENDING / MINI FIELD PENDING`
on the AUTH-MINI-01 implementation branch.

This contract is limited to the WeChat Mini Program client. It does not change
the already-authoritative backend auth routes, Flutter/Android contracts, UI V3,
or WeChat native SDK work.

## Registration and email verification

`POST /v1/auth/register` returns HTTP 201 `RegistrationResponse`:

```json
{
  "user_id": "<uuid>",
  "verification_required": true,
  "verification_delivery_pending": false
}
```

The Mini Program never treats this response as a login response. It stores no
access token, does not publish an owner, and does not call `/v1/user` after
registration. The Profile page tells the user to verify the email and offers
the existing `/v1/auth/resend-verification` route.

`POST /v1/auth/verify-email` is consumed as the existing
`EmailVerificationResponse`. A returned `session` is installed only after
strict validation of the complete `TokenResponse`. `already_verified` with a
null session remains unauthenticated; the client does not invent a token.

## Durable session authority

The only durable authenticated state is the complete `TokenResponse` stored
under the controlled Mini Program storage key `jiyi_auth_session`:

- `access_token`, `refresh_token`
- `session_id`, `user_id`, `token_type`
- `access_expires_at`, `refresh_expires_at`
- `account_deletion_in_progress`

Malformed, incomplete, or corrupt state is removed and treated as logged out.
The compatibility keys `jiyi_access_token` and
`jiyi_authenticated_user_id` are removed and are not authentication authority.
The current owner and auth-session epoch are derived from the validated
complete session. A random per-install UUID is stored separately as
`jiyi_auth_device_id`; no platform credential or fixed shared device ID is
used.

## Refresh, logout, and account switching

The coordinator refreshes shortly before access expiry and once after a 401.
Refresh calls use the current opaque refresh token, are single-flight per
session, and immediately replace it with the rotated response. A response
loss, malformed response, timeout, or replayed/invalid refresh clears the
local session; the old refresh token is never retried.

Logout fences the local epoch and clears the session before attempting the
server `/v1/auth/logout` call. The adapter checks the actual HTTP status and
returns `CONFIRMED` only for a 2xx response; network errors, 401/5xx responses,
and unknown completion are `UNCONFIRMED`. A failed network revoke cannot
restore the old account UI, and the result cannot clear or alter a newer login.
A new login clears the previous local authority before installing the new
complete session, so account switching cannot publish stale owner data.

Every protected request captures the owner, session id, and auth epoch before
I/O. Both success and error completion are rejected when that snapshot is no
longer current. A 401 refresh first compares the captured refresh token with
the current session; if another request already rotated it, the request uses
the new access token instead of replaying the old refresh token. A refresh
response whose user or session identity changes is rejected and not persisted.

Startup restore and foreground resume validate the same durable record and
perform a bounded refresh when needed. Existing `subscribeAuthSession`,
`currentAuthenticatedUserId`, `currentAuthSessionEpoch`, owner guards, and
session-generation fencing remain the consumer-facing APIs.

## Security and test contract

Provider tokens, email verification tokens, access tokens, and refresh tokens
are never logged or sent to analytics. The Mini Program does not locally
decide verification success or create a session. Tests use controlled
`Taro.request` and storage fakes to cover registration-without-session,
complete login/verify responses, malformed response fail-closed behavior,
expiry refresh, 401 single-flight, delayed-401 rotated-token non-reuse,
response-loss logout/switch fencing, login/verification attempt generations,
protected success/error fencing, remote logout status, refresh identity
continuity, storage corruption, and token-free errors. Profile publication is
also guarded by a page view generation and the captured validated session.

Backend PostgreSQL auth/session tests remain the authority for registration,
email verification, refresh rotation, logout, and session revocation; this
change adds no backend route, migration, provider credential, or deployment
configuration.
