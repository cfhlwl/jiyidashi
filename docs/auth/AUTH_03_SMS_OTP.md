# AUTH-03 SMS OTP

## Status

AUTH-03 implements the provider-neutral Auth V3 SMS capability with a fake/test
delivery seam. The default provider is disabled and production remains fail
closed until a separately approved server-side SMS provider activation.

AUTH-02E PNVS production activation is unchanged: `CODE READY / EXTERNAL
BLOCKED`. No provider credential is stored in this repository.

## Authority and contracts

`POST /v1/auth/phone/sms/request` accepts a canonical E.164 phone input,
installation metadata, and returns only `request_id`, `expires_at`, and
`cooldown_until`. The server canonicalizes the phone and controls delivery.

`POST /v1/auth/phone/sms/verify` accepts `request_id`, a six-digit code, and
installation metadata. It never accepts a client-asserted user or session.
Successful verification resolves or creates the existing
`AuthIdentity(provider=PHONE, subject=canonical E.164)` and calls the shared
AUTH-01 session issuer. `User.phone` is only a projection and is not a login
fallback.

The raw OTP is memory-only during provider delivery. The durable challenge
stores a server-keyed HMAC digest, request metadata, bounded attempt state, and
the resulting user/session references; it does not store the raw code.

## State, cooldown, and fencing

The durable challenge states are `PENDING`, `VERIFIED`, `EXPIRED`, `LOCKED`,
and `PROVIDER_ERROR`. A unique server-keyed active challenge key enforces one
active request per phone/install identity. Server cooldown is authoritative;
Flutter's timer is display-only. Provider I/O happens after the reservation is
committed and outside the identity/session transaction.

The Flutter gateway uses the existing unauthenticated auth generation and
serialized session-store mutation. Cancel, privacy revoke, route disposal, or
account switching invalidates the generation, so a late verify response cannot
persist or publish a stale session. Email remains available after SMS failure.

Consumer-safe errors include invalid, expired, too-many-attempts, cooldown,
rate-limited, unavailable/provider failure, account unavailable, and transient
transport failure. Provider internals and OTP values are not returned or logged.

## Capability and activation gates

The SMS row is shown only when `AuthCapabilities.smsOtpStatus` is
`AVAILABLE` and a gateway is supplied. The application default is email-only;
the disabled provider cannot make SMS available. A future live adapter must
remain server-side, supply delivery credentials through deployment secret
management, and preserve the same request/verify contract.

## Tests

Backend coverage includes disabled-provider fail-closed behavior, canonical
identity/session creation, server cooldown, invalid and expired codes, and
absence of raw OTP persistence. Flutter coverage includes single-flight
request/cooldown behavior and late verify completion after cancel.

AUTH-04 WeChat, AUTH-02E PNVS activation, and real SMS provider credentials are
outside this change.
