# AUTH-03 SMS OTP

## Status

AUTH-03 implements the provider-neutral Auth V3 SMS capability. AUTH-03P-A
adds the server-side Alibaba Cloud adapter and a production configuration seam;
the selector still defaults to disabled and production remains fail closed
until external provider activation is approved.

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
the disabled provider cannot make SMS available. The live adapter remains
server-side, supplies delivery credentials through deployment secret
management, and preserves the same request/verify contract.

AUTH-03P-B adds the single pre-login capability authority:
`GET /v1/auth/capabilities`. It returns only the provider-neutral statuses for
`email`, `sms_otp`, `phone_one_tap`, and `wechat`. It never returns Alibaba
configuration, credential state, SDK errors, endpoint, signature, or template
details. `sms_otp` is `AVAILABLE` only when the server-selected provider is
available and its complete production configuration is valid; provider factory
or network/configuration failures return `UNAVAILABLE`.

Flutter combines that server response with the native phone-one-tap probe and
the current privacy consent. A missing gateway, a capability request failure,
or revoked privacy hides SMS and preserves the email fallback. There is no
second local visibility authority and no cached `AVAILABLE` state that can
survive a failed refresh.

## AUTH-03P-B production readiness

The repository is `CODE READY / FIELD PENDING`, not `DONE`. The production
selector remains `disabled` until Alibaba service activation, billing/quota,
approved signature/template, least-privilege server credential delivery,
production backend access, and controlled mainland test devices/numbers are
confirmed outside Git. No real credential, OTP, or complete phone number is
part of this repository.

The safe activation contract is:

```text
AUTH_SMS_OTP_PROVIDER=aliyun
AUTH_SMS_OTP_ALIYUN_ENDPOINT=dysmsapi.aliyuncs.com
AUTH_SMS_OTP_ALIYUN_REGION=<approved region>
AUTH_SMS_OTP_ALIYUN_SIGN_NAME=<approved signature>
AUTH_SMS_OTP_ALIYUN_TEMPLATE_CODE=<approved template>
AUTH_SMS_OTP_ALIYUN_CREDENTIAL_SOURCE=environment
AUTH_SMS_OTP_ALIYUN_TIMEOUT_SECONDS=<bounded reviewed value>
```

The two AccessKey values, if the deployment has not yet moved to an approved
RAM-role/secret-manager delivery, are server-only environment or secret-manager
inputs. They are never passed to Flutter, stored in Git, printed, or returned by
the capability endpoint. In production, selecting `aliyun` with incomplete or
invalid configuration remains unavailable and cannot fall back to the fake
provider.

Rollback is configuration-only: set
`AUTH_SMS_OTP_PROVIDER=disabled`, restart/reload the backend, and the capability
endpoint hides SMS while preserving email and existing sessions. No migration
rollback is required.

## AUTH-03P-B field acceptance record

Real activation requires both an iOS physical-device run and an Android
physical-device run. Each run must record only a test-run ID, masked phone,
app/backend SHA, platform, timestamp, normalized JiYi result, provider request
ID, arrival yes/no, and bounded arrival latency. It must prove request, receipt,
verify, canonical `AuthIdentity(provider=PHONE, subject=E.164)`, canonical
session, restart recovery, logout, and relogin. Invalid/expired OTP, cooldown,
provider failure, privacy revoke, late response, and email fallback remain
release-blocking regressions.

Until those external and physical-device conditions are evidenced, the
classification is `CODE READY / FIELD PENDING` with the external prerequisites
listed as `EXTERNAL BLOCKED`; no SMS `AVAILABLE` or AUTH-03 `DONE` claim is
permitted in release documentation.

## AUTH-03P-A Alibaba Cloud adapter

The selected production adapter is Alibaba Cloud domestic SMS `SendSms` from
the `Dysmsapi/2017-05-25` API. The official API uses `PhoneNumbers`,
`SignName`, `TemplateCode`, and `TemplateParam`; the adapter sends only the
server-generated six-digit OTP as the `code` template variable. A canonical
mainland subject such as `+8613812345678` is converted to the domestic API
phone format `13812345678` inside the server adapter. Client code never holds
Alibaba credentials or calls this API.

The implementation uses the official Python package
`alibabacloud_dysmsapi20170525`, pinned in `backend/pyproject.toml` to
`4.6.0`. The official documentation specifies the package and generated
`send_sms_with_options` shape, but does not promise this repository pin as a
provider compatibility guarantee. The configured production endpoint must be
HTTPS; the current official mainland endpoint is
`https://dysmsapi.aliyuncs.com`. The configured region, approved sign name,
approved template code, credential source, and timeout are all required for
availability. `AUTH_SMS_OTP_ALIYUN_ENDPOINT` is the host
`dysmsapi.aliyuncs.com`; the adapter sets the SDK protocol to `https`. An
optional input in the form `https://dysmsapi.aliyuncs.com` is normalized to the
same host, while HTTP URLs, credentials, ports, paths, queries, fragments,
other hosts, and empty values fail closed. Missing or unsupported configuration returns
`AUTH_SMS_OTP_UNAVAILABLE`; it never falls back to the fake provider.

The adapter uses server-side AccessKey material delivered through deployment
environment/secret management, with no credential values in Git or logs.
The deployment may provide the two credential values through the official
`ALIBABA_CLOUD_ACCESS_KEY_ID` and `ALIBABA_CLOUD_ACCESS_KEY_SECRET` environment
names; the app-specific `AUTH_SMS_OTP_ALIYUN_*` names are also accepted by the
configuration seam.
Alibaba recommends a RAM user with least privilege and a RAM Role or other
secret-management approach for production. The repository currently supports
the explicit `environment` source only; a RAM Role implementation remains an
external deployment decision and is not silently assumed.

Each challenge makes exactly one provider call. SDK autoretry is disabled and
the runtime maximum is one attempt, because a timeout or transport failure can
leave SMS delivery ambiguous. Provider responses normalize to
`UNAVAILABLE`, `RATE_LIMITED`, `TIMEOUT`, or `PROVIDER_ERROR`. A successful
response must contain `Code=OK` and `RequestId`; that request ID is stored in
the existing challenge `provider_request_id` field. Raw provider responses,
OTP values, complete phone numbers, and credentials are not logged.

### Official Provider Evidence

- [Alibaba Cloud SMS Python SDK](https://help.aliyun.com/en/sms/developer-reference/using-python-openapi-example)
  documents the official package, server-side credentials, generated client,
  `SendSmsRequest`, `send_sms_with_options`, endpoint configuration, and the
  `RequestId` response field.
- [Alibaba Cloud domestic SendSms API](https://help.aliyun.com/zh/sms/developer-reference/api-dysmsapi-2017-05-25-sendsms)
  documents the domestic RPC operation and its request fields.
- [Alibaba Cloud SMS API overview](https://help.aliyun.com/en/sms/developer-reference/api-dysmsapi-2017-05-25-overview)
  documents the `Dysmsapi/2017-05-25` product/API family.

Official docs do not define a universal retry-safe contract for an SMS send
whose HTTP result is unknown. Therefore this adapter does not retry any
ambiguous result. Provider billing, quota, approved signature/template, RAM
policy, production credential delivery, and real-device acceptance remain
external activation prerequisites.

After a provider attempt fails or has an unknown completion state, the durable
challenge enters `PROVIDER_ERROR` but retains its active key through
`cooldown_until`. A same-phone/same-device resend during that period returns
`AUTH_SMS_OTP_COOLDOWN` without another provider call. Once the durable
cooldown expires, the old challenge is released and a new request may make one
new provider call. The active key remains device-scoped, so the existing
policy for a different device is unchanged.

## Tests

Backend coverage includes disabled-provider and production-fake fail-closed
behavior, missing-config fail closed, official request mapping, request-ID
capture, response/error normalization, one-call/no-blind-retry behavior,
canonical identity/session creation, server cooldown, invalid and expired
codes, and absence of raw OTP persistence. The Alibaba transport is injected
in tests; CI never calls the real endpoint. Flutter coverage includes
single-flight request/cooldown behavior and late verify completion after
cancel.

AUTH-04 WeChat, AUTH-02E PNVS activation, and real SMS provider credentials are
outside this change.
