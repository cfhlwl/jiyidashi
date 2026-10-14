# AUTH-006 账号与安全中心 V1

## Status

CODE / MOCK / UX only. The production identity-link provider remains disabled and
live link/unlink plus field acceptance are blocked on a real provider and recent
reauthentication proof. This document records the client contract; it does not
create a second identity or session authority.

## Authority and trust boundary

- `GET /v1/auth/identities` is the only source for the identities shown by the
  Flutter and WeChat Mini Program account-security pages.
- `subject_hint`, `verified_at`, and `linked_at` are server-owned projections.
  Clients never infer an identity from profile email, `User.phone`, nickname,
  openid, unionid, or a capability intended for login.
- Client link/unlink adapters accept only opaque provider proof and independent
  recent reauthentication proof. They never accept profile text, access tokens,
  or client assertions as identity authority.
- Every request is bound to the current owner/session version/epoch. A late A
  response cannot publish into B, and malformed responses fail closed.

## Provider state

`AUTH_IDENTITY_LINK_PROVIDER=disabled` remains the production-safe default.
The UI therefore exposes the real identity list and clearly disables bind/unbind;
it sends zero mutation requests. The typed adapters and mock HTTP tests exist for
future provider work only. No fake provider, secret, native SDK, or production
configuration is enabled by AUTH-006.

## Error and lifecycle contract

401, 403, 423, 429, transport failure, malformed protocol, operation conflict,
in-progress, and unknown-operation states are mapped to consumer-safe messages.
Conflict responses do not reveal another account. Refresh and account changes
invalidate the page generation; stale results, errors, busy state, dialogs, and
identity lists are discarded.

## Implemented surfaces

- Flutter: typed `AuthIdentityRead` / mutation response adapters, independent
  Account & Security page, Profile navigation entry, provider-off disabled UX.
- WeChat Mini Program: strict identity parsers and typed adapters, independent
  account-security route, Profile navigation entry, provider-off disabled UX.
- Tests: strict parser/transport tests, masked-list rendering, no-mutation
  provider-off behavior, and current-session request binding.

## Explicit gaps

Live bind/unbind UX remains intentionally unavailable until a separately reviewed
provider/step-up task supplies verified opaque proof and production capability
configuration. This PR does not change backend AUTH-005, migrations, session
rotation, real SMS/WeChat providers, or field acceptance.
