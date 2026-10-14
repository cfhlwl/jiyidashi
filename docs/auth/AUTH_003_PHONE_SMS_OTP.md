# AUTH-003 Phone SMS OTP registration/login

## Status

`CODE / MOCK READY · REAL SMS PROVIDER OFF · FIELD PENDING`

This change adds the phone verification-code registration/login contract on top
of the already merged AUTH-01 canonical identity and AUTH-03 provider-neutral
SMS service. The repository never enables a real SMS provider, sends a paid
message, or stores a provider credential.

## Authority matrix

| Boundary | Authority | Client responsibility |
| --- | --- | --- |
| Phone input | Backend canonicalization and OTP verification | Submit a user-entered E.164 value; never claim it is verified |
| OTP | Backend challenge row plus server-keyed HMAC digest | Keep the code in memory only and submit it once |
| Phone identity | `AuthIdentity(provider=PHONE, subject=canonical E.164)` | Never read `User.phone` as a login fallback |
| Account | `User.id` resolved by AUTH-01 | Never choose or merge an owner locally |
| Session | Existing durable AUTH-01 session issuer | Persist only the standard `TokenResponse` through the existing session store |
| Delivery capability | `GET /v1/auth/capabilities.sms_otp` | Hide the action unless the server says `AVAILABLE` |

An unrecognized verified phone creates one new PHONE identity and its canonical
user through `create_user_for_verified_identity`. An existing PHONE identity
resolves its existing user. No email account or legacy `User.phone` projection
is automatically merged or claimed. Explicit identity linking remains a
separate authenticated operation.

## End-to-end contract

```text
capability AVAILABLE
  -> phone input
  -> POST /v1/auth/phone/sms/request
  -> durable PENDING challenge + provider delivery
  -> server cooldown / client display timer
  -> POST /v1/auth/phone/sms/verify
  -> one-time challenge consumption
  -> AUTH-01 PHONE identity resolve/create
  -> standard durable JiYi session
```

The request accepts `phone`, `device_id`, `client_platform`, and optional
`device_name`. The verify request accepts only `request_id`, the six-digit
`code`, and installation metadata; it does not accept a user id, phone, or
session claim. The response is the existing `TokenResponse`.

The server accepts only canonical E.164 strings (`+` followed by a non-zero
country code and 7–14 further digits). It does not guess a region or normalize
local-format strings into a new identity.

## OTP state and abuse controls

`AuthSmsOtpChallenge` is the durable authority. It stores a server-keyed HMAC
digest, request metadata, attempt counters, cooldown/expiry, provider request
id, and resolved session references; it never stores the raw OTP. States are
`PENDING`, `VERIFIED`, `EXPIRED`, `LOCKED`, and `PROVIDER_ERROR`.

The request path applies persistent IP, device, and canonical-phone limits,
then takes a durable `(phone, device)` active-key reservation before provider
I/O. Provider failure/unknown completion retains the active key until the
cooldown expires, so an immediate resend cannot multiply cost. Verify applies
persistent IP/request limits and row locking; concurrent valid attempts have at
most one winner. All provider calls are injected fakes in this phase.

`AUTH_SMS_OTP_PROVIDER=disabled` is the default. `fake` is accepted only in a
non-production test/development process and is never reported as a public
production capability. The production Alibaba adapter remains server-side and
fail-closed until separate activation and field approval.

## Client contracts

Flutter uses the existing `SmsOtpGateway` and `SmsOtpPage`: request and verify
are single-flight, the cooldown is display-only, and cancel/route disposal/
privacy/session-generation fences prevent late results from installing a
session. The raw code is only held by the page controller.

The Mini Program uses `requestSmsOtp` and `verifySmsOtp` in `services/api.ts`.
The page displays the SMS entry only when the server capability is
`AVAILABLE`; its request id, phone, and code are in component memory only.
Its verify path uses `authAttemptGeneration` and `authSessionEpoch` before
installing a response, so an account switch or logout rejects a stale result.
The existing email/password and WeChat Mini Program paths remain unchanged.

## Test and deployment boundary

Unit tests cover disabled/fake provider behavior, canonical new and existing
PHONE identities, auth-disabled hard deny, invalid/expired/replayed codes,
cooldown, provider failure, raw-code absence, client fencing, and strict
response parsing. `backend/tests/postgres_auth_sms_otp_integration.py` is an
explicit real-PostgreSQL gate for concurrent verification and same-device
send reservation; SQLite is not evidence for that gate.

This phase does not configure Alibaba AppKey/Secret, alter production
configuration, send real SMS, or claim iOS/Android/Mini physical-device
acceptance. Remaining field blockers are provider account activation,
approved signature/template and quota, server secret-manager delivery, and
controlled carrier/device runs.
