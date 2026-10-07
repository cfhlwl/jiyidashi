# AUTH-02 Phone One-Tap Login V1

Status: **AUTH-02A / SPEC AND AUDIT ONLY**

This document locks the provider, authority boundaries, security model, and
implementation gates for carrier phone one-tap login. It does not authorize a
backend route, migration, database table, SDK installation, native change,
Flutter change, UI change, provider scheme creation, credential submission, or
production activation.

Audited: 2026-10-07 (Asia/Shanghai)

Out of scope: UI V3 visual parity, Memory/Life/Family UI, APP-ID-001 work,
SMS OTP/AUTH-03, WeChat/AUTH-04, push, and every other provider.

## Status

- `AUTH-UI-01`: closed.
- `AUTH-01`: closed and treated as the identity/session authority.
- `APP-ID-001`: merged at `b2f3d92aeb9afde8b4e6118664359cd49504f045`.
- This branch is based directly on the execution-time `origin/main` at that
  commit.
- No AUTH-02 production implementation exists on this branch or in `main`.
- Official provider evidence is **PARTIAL**: the core product/API contract is
  documented, but critical token TTL/retry details are inconsistent or absent.
- AUTH-02A is ready for narrow review only. It is not production-ready.

## Current Repository Baseline

Baseline:

```text
origin/main: b2f3d92aeb9afde8b4e6118664359cd49504f045
branch: codex/auth-02a-phone-one-tap-spec-20261007
HEAD: b2f3d92aeb9afde8b4e6118664359cd49504f045
merge-base: b2f3d92aeb9afde8b4e6118664359cd49504f045
```

The audit was read-only. The only file authorized for this phase is this
document.

Relevant existing authority:

| Area | Existing decision/evidence |
| --- | --- |
| Provider enum | `backend/app/auth_models.py` has `EMAIL_PASSWORD`, `PHONE`, and `WECHAT`; there is no one-tap provider. |
| Identity key | `AuthIdentity(provider, subject)` is unique; `AuthIdentity.user_id` owns the account relationship. |
| Phone subject | `canonicalize_phone_subject()` accepts only an already canonical E.164 string. |
| Lookup | `resolve_auth_identity()` intentionally does not use `User.phone` as a fallback login lookup. |
| New identity | `create_user_for_verified_identity()` creates User, AuthIdentity, projection, and default entitlement through the AUTH-01 transaction pattern. |
| Session | `issue_authenticated_session()` and `create_public_session()` are the shared session authority. Access JWTs are bound to durable `AuthSession` rows; provider tokens are not session credentials. |
| Refresh security | Raw refresh tokens are returned to the client, while the server persists only a server-keyed digest and refresh receipts. |
| Deletion | Known, linked, successfully re-authenticated identities may receive the existing deletion-continuation response; ordinary data access remains fenced. |
| Disabled accounts | `User.auth_disabled_at` is a hard deny for session issuance and authenticated access. |
| Abuse controls | `AuthRateLimitBucket` is a durable, HMAC-keyed database rate-limit authority shared across workers. Current policies cover email/password, verification, reset, refresh, and authenticated APIs, but there is no phone one-tap policy yet. |
| Current auth API | `backend/app/api/auth.py` exposes email/password, email verification, refresh, logout, and recovery routes; no phone one-tap route exists. |
| Mobile session | `mobile/lib/auth_session_store.dart` persists the JiYi refresh token and session id in secure storage. This is existing JiYi session persistence and must remain the only durable client credential path. |

The repository audit covered the requested auth, security, PostgreSQL
integration-test, mobile session/API, native project, and release identity
paths. Existing AUTH-01 tests already cover phone canonicalization, phone
identity creation, duplicate/concurrent identity ownership, account deletion,
disabled accounts, and session behavior. AUTH-02B must add provider-exchange
tests without replacing those authorities.

## Provider Decision

The V1 provider is locked to **Alibaba Cloud Phone Number Verification Service
(PNVS), 号码认证服务**, using the native Android and iOS SDKs and the App-side
one-click-login flow.

The provider flow is:

```text
iOS/Android native PNVS SDK
  -> operator authorization page
  -> explicit user consent
  -> provider login token
  -> JiYi backend
  -> Alibaba Cloud GetMobile
  -> verified phone number
  -> canonical E.164
  -> AuthProvider.PHONE
  -> AUTH-01 resolver/create authority
  -> shared JiYi session issuance
```

There is no `AuthProvider.ONE_TAP`, `AuthProvider.ALIYUN`, or other permanent
one-tap identity. One-tap is a verification method. A future SMS ceremony is
also a verification method for the same `AuthProvider.PHONE` identity.

## Official Provider Evidence

Authority used: Alibaba Cloud Help Center and its linked official OpenAPI/SDK
documentation only. No blog, forum, CSDN, or third-party tutorial is an
authority for this design.

Official evidence:

1. [PNVS product overview](https://help.aliyun.com/zh/pnvs/product-overview/what-is-the-number-certification-services)
   documents one-click login as operator data-network authentication that
   displays a masked number and requires user agreement before confirmation.
2. [Android native client access](https://help.aliyun.com/zh/pnvs/developer-reference/the-android-client-access)
   documents the Android SDK, `checkEnvAvailable`, `setAuthSDKInfo`,
   `accelerateLoginPage`, `getLoginToken`, and `quitLoginPage`. It lists
   `minSdkVersion >= 21`, `compileSdkVersion >= 30`, network permissions, and
   package/signature configuration.
3. [iOS native client access](https://help.aliyun.com/zh/pnvs/developer-reference/the-ios-client-access)
   documents `setAuthSDKInfo`, `checkEnvAvailableWithAuthType`,
   `accelerateLoginPageWithTimeout`, `getLoginTokenWithTimeout`, and
   `cancelLoginVCAnimated`.
4. [PNVS scheme management](https://help.aliyun.com/zh/pnvs/user-guide/number-certification-program-management/)
   documents that a native scheme is associated with the app package/package
   signature on Android and Bundle ID on iOS, and that the scheme produces a
   PNVS scheme key. It also documents the three-main-operator scope, the
   default-data-SIM rule for dual-SIM phones, and unsupported international,
   Hong Kong, Macao, Taiwan, Broadnet, IoT, and traffic-card cases.
5. [GetMobile](https://help.aliyun.com/zh/pnvs/developer-reference/api-dypnsapi-2017-05-25-getmobile)
   documents the server-side one-click number exchange. `AccessToken` is the
   App SDK login token; `OutId` is optional; success returns `Mobile` and a
   provider `RequestId`; `dypns:GetMobile` is the RAM action. The page states
   that the end user must have confirmed the SDK authorization page and must not
   be simulated or bypassed. It also documents the provider QPS limit shown on
   that page as 5000 requests/second per user.
6. [PNVS compliance guidance](https://help.aliyun.com/zh/pnvs/security-and-compliance/number-certification-service-compliance-guidelines)
   documents the SDK data collection categories (network type, IP, device
   information, OS, and SIM state as applicable) and requires the app's privacy
   policy consent before PNVS SDK initialization.
7. [PNVS Android FAQ](https://help.aliyun.com/zh/pnvs/support/the-android-client-faq)
   documents that the feature depends on data connectivity, does not support
   emulators, uses the default mobile-data SIM on dual-SIM devices, supports
   data or data+Wi-Fi with a possible network switch, and treats missing SIM,
   disabled data, or missing network permission as environment failures. It
   also states support for China Mobile, China Unicom, and China Telecom
   authenticated mobile cards, excluding IoT/traffic cards.
8. [PNVS framework support and server integration](https://help.aliyun.com/zh/pnvs/user-guide/number-certification-program-management/)
   states that native Android/iOS SDKs and a UniApp plugin exist, but there is
   no official Flutter plugin; Flutter integration must be developed through a
   native bridge.
9. [PNVS server SDK reference](https://help.aliyun.com/zh/pnvs/developer-reference/server-side-sdk-reference/)
   recommends the maintained V2.0 server SDK family. AUTH-02B may use the
   official OpenAPI client behind a provider-neutral adapter, but the business
   layer must not depend on Alibaba SDK types.

### Evidence matrix

| Question | Result | Design consequence |
| --- | --- | --- |
| Android native SDK | Confirmed | AUTH-02C uses an Android adapter. |
| iOS native SDK | Confirmed | AUTH-02C uses an iOS adapter. |
| Mainland Mobile/Unicom/Telecom | Confirmed | Acceptance matrix must cover all three. |
| Flutter official plugin | Not available in official evidence | Design a JiYi bridge; do not add a third-party plugin. |
| Data/Wi-Fi network | Confirmed: data required; data+Wi-Fi may switch to data | Availability must fail closed if data/SIM/network prerequisites fail. |
| Dual SIM | Confirmed: current/default data SIM only | Do not promise selection of the non-data SIM. |
| No SIM/no data | Confirmed as unavailable conditions | Fall back to email in this phase. SMS is out of scope. |
| Authorization page | Confirmed; explicit consent required | No simulated click, auto-confirm, or bypass. |
| Client token | Confirmed as `AccessToken` input to GetMobile | Treat it as opaque transient verification material. |
| GetMobile output | Confirmed: `Mobile`, `RequestId`, `Code`, `Message` | Only the server may convert `Mobile` into PHONE identity. |
| RAM permission | Confirmed: `dypns:GetMobile` | Use least privilege and server-only credentials. |
| Token single-use | Confirmed by GetMobile page and FAQ | JiYi must reject reuse and never blindly retry a consumed token. |
| Token TTL | **OFFICIAL_EVIDENCE_INCOMPLETE** | See Token Lifecycle; do not hard-code an unverified value. |
| Token/app binding | Partially documented through scheme/package/signature/key matching; exact cryptographic binding is not specified | Treat a binding mismatch as unavailable/provider error; verify exact semantics before production. |
| Provider idempotency | Not documented for GetMobile | JiYi must supply durable exchange idempotency; provider retries are conservative. |
| Provider error taxonomy | Raw error center exists, but the full retry/consumption contract is not established here | Normalize to JiYi codes and verify the selected SDK/API version in AUTH-02B. |

### Critical token evidence gap

The current official GetMobile page states:

- China Telecom: 10 minutes, once;
- China Unicom: 30 minutes, once;
- China Mobile: 2 minutes, once.

The current official Android FAQ states the same 10-minute/2-minute values but
states China Unicom as 60 minutes. These official pages conflict. The exact
TTL is therefore **UNRESOLVED / OFFICIAL_EVIDENCE_INCOMPLETE**. AUTH-02B must
reconcile the current SDK/API version, console documentation, and operator
behavior before using TTL for reservation expiry, client messaging, or tests.
No value in this document overrides the provider.

The official material also does not guarantee that GetMobile is idempotent
after a successful provider exchange, nor does it expose a recovery query for
an ambiguous timeout. JiYi must provide the durable receipt and safe unknown
state defined below.

## App Identity / Signing Dependencies

Current repository identity is fixed:

| Target | Current value |
| --- | --- |
| Android `applicationId` | `com.jiyidays` |
| Android namespace/package | `com.jiyidays` |
| iOS Bundle ID | `com.jiyidays` |
| iOS RunnerTests | `com.jiyidays.RunnerTests` |
| iOS BGTask identifier | `com.jiyidays.passive-recovery` |

Android PNVS scheme creation must use `com.jiyidays` plus the final release
certificate fingerprint. A debug certificate is not a production authority.
The Android release-signing infrastructure is ready, but final key material is
pending. Apple App ID registration and Google Play registration are not
externally verified. PNVS scheme creation, billing/account activation, and
provider credentials are not complete.

Consequences:

- AUTH-02A specification is not blocked by these external items.
- AUTH-02B fake-provider/backend design can proceed without them.
- AUTH-02C may develop non-final adapter wiring only; it may not claim
  production readiness.
- AUTH-02E production scheme binding is blocked until the final Android
  certificate and Apple identity/registration are available and verified.

## Locked AUTH-01 Authority

The permanent authority remains:

```text
(AuthProvider.PHONE, canonical E.164)
    -> AuthIdentity.user_id
    -> User.id
```

`User.id` is the canonical account owner. `AuthIdentity` is the login identity
authority. `User.phone` is only a projection/contact field. `ONE_TAP` is not an
enum value and must not become an identity provider.

Provider verification occurs before canonicalization and identity lookup. A
provider token, masked number, UI text, authorization code, or client-provided
phone is never a permanent subject.

## End-to-End Flow

The target flow is:

```text
Unauthenticated Auth Surface
  -> native availability check
  -> optional bounded pre-login/acceleration
  -> provider authorization page
  -> user explicitly confirms consent
  -> native SDK obtains opaque login token
  -> Flutter receives typed JiYi result
  -> POST /v1/auth/phone/one-tap
  -> anonymous abuse gate
  -> replay/idempotency reservation
  -> Alibaba GetMobile external I/O
  -> verified phone result
  -> canonical E.164
  -> AUTH-01 resolve_auth_identity(PHONE)
  -> if absent: create_user_for_verified_identity(PHONE)
  -> issue_authenticated_session()
  -> existing TokenResponse shape
  -> existing secure JiYi session persistence
  -> Consumer Shell
```

The provider token is never a JiYi access token. The client never sends
`phone`, `mobile`, or `masked_phone` as authentication authority. `device_id`,
platform, and device name are request metadata only and are not proof of
ownership.

## Native Bridge Contract

Design only; no native code is authorized in AUTH-02A.

Provider-neutral Flutter-facing abstraction:

```text
PhoneOneTapBridge
  availability() -> Future<PhoneOneTapAvailability>
  prepare() -> Future<PhoneOneTapResult>
  login() -> Future<PhoneOneTapResult>
  dismiss() -> Future<void>
```

`prepare()` is a bounded, optional pre-login/acceleration operation. It is not
called at app startup, while a valid JiYi session exists, or before JiYi privacy
prerequisites are satisfied. `dismiss()` is idempotent and must be safe after
the native page has already disappeared.

The bridge exposes JiYi states, not raw Alibaba result codes:

```text
AVAILABLE
UNAVAILABLE
USER_CANCELLED
SWITCH_TO_OTHER_METHOD
TOKEN_ACQUIRED
PROVIDER_ERROR
TIMEOUT
```

`TOKEN_ACQUIRED` carries only an opaque in-memory `login_token` for immediate
submission to the backend. It is never written to secure storage, analytics,
crash reports, logs, or Flutter state that outlives the exchange. Raw provider
codes may remain in a server/native diagnostic boundary only when the privacy
and retention policy permits; they are not part of the Flutter domain contract.

The Alibaba adapters map native SDK results as follows:

```text
Aliyun raw SDK result
  -> provider adapter mapping
  -> PhoneOneTapResult
```

Unknown raw outcomes fail closed as `PROVIDER_ERROR` or `TIMEOUT`, according to
whether completion is known or ambiguous.

## Capability Model

Production capability is true only when all of the following hold:

- supported physical OS/device and supported native SDK are present;
- PNVS initialization succeeds after JiYi privacy consent;
- package/Bundle ID, scheme, key, and final signing identity match;
- current carrier/data-SIM environment is supported;
- required mobile-data/network permissions and network path are available;
- provider account, scheme, and service activation are valid;
- no bounded timeout or provider maintenance result is active.

Any required condition failing means `PHONE_ONE_TAP = unavailable`. The UI may
not render a false successful action. Current fallback is email. SMS OTP is a
future AUTH-03 path and is not part of this capability contract.

## Backend API Contract

Design only:

```text
POST /v1/auth/phone/one-tap
```

Request fields:

| Field | Meaning | Authority rule |
| --- | --- | --- |
| `login_token` | Opaque native PNVS token | Verification input only; never a JiYi bearer token. |
| `request_id` | Client retry/idempotency key for one exchange | Must be reused for a retry of the same native exchange; must not be reused with another token. |
| `device_id` | Existing install/device metadata | Abuse signal and session metadata only; spoofable. |
| `client_platform` | `android`/`ios` or reviewed equivalent | Diagnostics/metadata only. |
| `device_name` | Optional display metadata | Never identity authority. |

The request must reject `phone`, `mobile`, and `masked_phone` as extra or
authentication-bearing fields. Server validation must not silently accept or
trust them.

The response reuses the existing `TokenResponse` fields, including:

```text
access_token
refresh_token
session_id
token_type
user_id
access_expires_at
refresh_expires_at
account_deletion_in_progress
```

No new session authority, provider bearer format, or provider-specific response
schema is introduced.

## Provider Adapter

The business layer depends on this provider-neutral boundary:

```text
PhoneOneTapProvider.exchange_login_token(
    login_token,
    request_id,
    client_platform,
    provider_context,
) -> VerifiedPhoneResult | ProviderExchangeError
```

The Alibaba implementation is conceptually:

```text
AliyunPnvsPhoneOneTapProvider
  -> official GetMobile API/SDK
  -> VerifiedPhoneResult
```

`VerifiedPhoneResult` contains only the information needed after successful
verification:

- verified phone value from the provider;
- provider verification timestamp, if supplied, otherwise server receipt time
  is explicitly labelled as receipt time rather than verification time;
- provider request id;
- normalized provider/carrier diagnostics where needed for operations.

Carrier/provider metadata is diagnostic, not identity authority. Alibaba SDK,
OpenAPI DTOs, AccessKey material, scheme keys, and raw provider errors must not
cross this boundary into the domain or client contract.

## Token Lifecycle

1. Native PNVS obtains a token only after the provider authorization page and
   explicit user consent.
2. Flutter forwards it immediately with a new `request_id`.
3. JiYi computes a server-keyed token fingerprint and discards the raw token
   after the provider call/receipt path completes.
4. JiYi calls GetMobile only from the server, over the official endpoint/client
   path, using server-only credentials.
5. The verified provider number is canonicalized to E.164 before identity
   resolution.
6. The raw token is never persisted or logged. Only a keyed fingerprint and
   exchange metadata are retained.
7. Because the official TTL evidence conflicts for China Unicom, no hard-coded
   operator TTL is authorized in V1 design. AUTH-02B must configure a reviewed
   provider TTL/lease policy after reconciling the current official source.
8. Provider single-use is treated as authoritative. A duplicate or consumed
   token is never retried against GetMobile.

The fingerprint should be HMAC-SHA-256 using a dedicated server secret and a
versioned domain separator, for example:

```text
HMAC(phone-one-tap-token-v1, login_token)
```

The JWT secret must not be reused if a separate exchange-fingerprint secret can
be provisioned. Fingerprint rotation must preserve enough versions to resolve
unexpired ledger rows, or migrate fingerprints without exposing raw tokens.

## Replay / Idempotency Model

The exchange is a durable state machine, not an in-memory map:

```text
RESERVED
  -> PROVIDER_SUCCEEDED
  -> IDENTITY_RESOLVED
  -> COMPLETED

RESERVED -> PROVIDER_REJECTED
RESERVED -> PROVIDER_UNKNOWN
```

Required request semantics:

| Input relationship | Required result |
| --- | --- |
| Same token + same `request_id` while in progress | Return a bounded in-progress/retry-safe response; never run a second provider call concurrently. |
| Same token + same `request_id` after `COMPLETED` | Do not call GetMobile again. Reuse the recorded user/exchange result and issue a normal JiYi session response without creating another User. Raw token is not recovered. |
| Same token + different `request_id` | Fail closed as `AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED`. |
| Same `request_id` + different token | Fail closed as `AUTH_PHONE_ONE_TAP_CONFLICT`. |
| Provider success + HTTP response lost | A later same-request retry uses the durable receipt; it never calls GetMobile again and cannot create another User. |
| Provider token consumed + provider response lost before JiYi sees success | Mark/return `PROVIDER_UNKNOWN` or `AUTH_PHONE_ONE_TAP_TIMEOUT`; do not guess success and do not retry the consumed token. A new native token and new request id may be attempted. |

The exact same access/refresh strings need not be returned after an HTTP
response loss: raw refresh material is intentionally not stored server-side.
The safe deterministic guarantee is the same exchange outcome/user authority,
provider non-reuse, and a newly issued standard JiYi session when policy allows.

`request_id` and token fingerprint uniqueness must be enforced under database
transaction/unique-key authority, not only in a process-local cache.

## Durable Exchange Decision

**Decision: AUTH-02B requires a durable `PhoneOneTapExchange` ledger or an
equivalent durable replay/idempotency model.**

An in-memory cache is insufficient because:

- multiple web workers can receive the same retry concurrently;
- process restart would lose consumed-token state;
- a provider token is single-use and may be consumed before the response is
  delivered;
- response loss must not create a second User or a second provider charge;
- multi-instance deployments need one shared request/token authority;
- a local semaphore cannot provide durable replay or cross-instance safety.

Redis is not the current formal repository authority for this contract. A
process-local cache or an unreviewed Redis best-effort key is therefore not
acceptable as the only ledger.

Conceptual ledger fields (design only; no migration in AUTH-02A):

```text
id                    durable exchange id
request_id            unique client idempotency key
token_fingerprint     HMAC digest; never raw token
state                 RESERVED / PROVIDER_SUCCEEDED / IDENTITY_RESOLVED /
                      COMPLETED / PROVIDER_REJECTED / PROVIDER_UNKNOWN
client_platform       normalized metadata
device_fingerprint    optional HMAC install/device signal, not authority
provider_request_id   provider receipt id when available
resolved_user_id      canonical User.id when resolved
session_id            JiYi session receipt id when issued; not a bearer token
verified_at           provider verification time when available
error_code            normalized JiYi/provider outcome
created_at
updated_at
expires_at            reviewed reservation/retention deadline
completed_at
```

The ledger must not store raw `login_token`, full provider credentials, or an
unnecessary clear-text phone value. `resolved_user_id` and the canonical
identity tables are sufficient to replay a completed logical outcome. If a
later recovery requirement needs the phone value, it must be justified by a
separate reviewed encrypted-PII policy; it is not permitted by this spec.

Retention must be long enough to cover the provider token lifetime, bounded
client retries, and the deployment's response-loss window. It must have a
reviewed purge policy and must not be shorter merely because a process
restarted.

## Transaction Boundary

This is a hard boundary:

```text
anonymous rate gate
  -> short transaction: reserve exchange
  -> COMMIT
  -> external Alibaba GetMobile I/O
  -> short transaction: record provider result, resolve/create identity,
     issue the existing JiYi session, and finalize the exchange receipt
  -> COMMIT
```

No Alibaba network call may occur while holding:

- a `User FOR UPDATE` lock;
- an AuthIdentity conflict/creation transaction;
- a session-critical transaction;
- an entitlement or account-deletion critical lock.

AUTH-02B must use the existing AUTH-01 helpers and, if necessary, add an
internal transaction-aware orchestration seam so the exchange receipt and
identity/session outcome have a crash-safe boundary. It must not create a
second session authority or copy provider-specific account creation logic.

If a worker dies after provider success but before finalization, the ledger
must remain in a recoverable state. A same-request retry may finalize from the
recorded provider result; if the result was never received, it must return the
safe unknown state and require a newly obtained provider token.

## Identity Resolution

After `GetMobile` succeeds:

1. Validate the provider response shape and reject masked, malformed, or
   non-canonical values.
2. Canonicalize the verified provider number to E.164 using
   `canonicalize_phone_subject()`.
3. Resolve only:

   ```text
   AuthIdentity(provider=AuthProvider.PHONE, subject=canonical_e164)
   ```

4. If present, load its `user_id` and preserve that canonical owner.
5. Re-check `auth_disabled_at` and the account-deletion boundary under the
   AUTH-01 lock ordering.
6. Issue the existing provider-neutral session response.

A client-submitted phone, masked display number, `User.phone` projection, or
carrier metadata can never participate in this lookup.

## New User Creation

If the verified PHONE identity does not exist, use only
`create_user_for_verified_identity(provider=PHONE, subject=canonical_e164,
verified_at=provider_verification_time)`.

The AUTH-01 atomic transaction owns:

- the new `User`;
- the PHONE `AuthIdentity`;
- the `User.phone` E.164 projection;
- the default entitlement.

The unique `(provider, subject)` authority must elect one owner under a
first-ever login race. A losing request resolves the winner or returns a
durable exchange outcome; it never creates a second User, silently transfers
identity ownership, or merges an email account.

## Legacy Projection Rules

`User.phone` remains a projection. If it contains `+86138...` but no matching
`AuthIdentity(provider=PHONE, subject=+86138...)` exists, one-tap login must not
claim that User. It creates/resolves only through the identity authority.

Any historical projection reconciliation or linking requires an explicit,
reviewed migration/AUTH-05 policy. It is not part of AUTH-02.

## Account Deletion

Use the existing AUTH-01 semantics without a new deletion authority:

- A known existing PHONE identity plus active deletion operation plus successful
  provider re-authentication may receive the existing deletion-continuation
  session response with `account_deletion_in_progress=true`.
- Ordinary user data APIs remain fenced with the existing 423 behavior.
- The continuation must not create an identity, change a projection, restore a
  normal account, or create a second User.
- An unknown PHONE identity must not be matched to a deleting User by looking at
  `User.phone`.
- Delete/logout/session fencing must use the existing session service and lock
  order.

## Auth Disabled

`auth_disabled_at` is a hard deny. Even after a successful GetMobile result,
JiYi must return the existing `AUTH_ACCOUNT_UNAVAILABLE` semantic and must not:

- create a normal session;
- create a replacement User;
- transfer the identity;
- change the projection;
- bypass the disabled account.

The provider result may be retained only as a restricted exchange outcome
according to the ledger retention policy; it is not permission to authenticate.

## Concurrency

Required invariants and cases:

| Case | Required invariant |
| --- | --- |
| Same token concurrent requests | One durable reservation/provider call; followers reuse/wait for the same receipt or receive a bounded safe state. |
| Same phone, different valid tokens | The unique `(PHONE, E.164)` identity elects one canonical User; both successful exchanges may issue sessions for that User. |
| First-ever PHONE login race | One User, one PHONE identity, one projection, one default entitlement. |
| Existing PHONE concurrent login | Both resolve the existing `AuthIdentity.user_id`; neither creates or transfers ownership. |
| Provider timeout + retry | No blind GetMobile retry with a token whose consumption is unknown; same request returns safe unknown state; new token/new request may retry. |
| Provider success + response loss | Durable exchange receipt prevents a second User and a second GetMobile call. |
| Disable/delete racing with callback | User/deletion lock ordering wins; disabled is hard deny, known deletion is continuation only. |

The final invariant is:

```text
one (AuthProvider.PHONE, canonical E.164)
  -> at most one AuthIdentity.user_id
  -> exactly one canonical User.id when linked
```

## Abuse / Cost Controls

GetMobile is an external, billable/quota-bearing call. The provider's documented
QPS limit is not a safe JiYi application limit.

AUTH-02B must add reviewed controls for:

- per-source IP anonymous exchange attempts;
- per-install/device signal where safe, treating it as spoofable;
- request-id creation/reuse abuse;
- token-fingerprint abuse and replay attempts;
- provider global concurrency across all backend instances;
- optional per-IP/device/provider concurrency;
- bounded provider timeout;
- response-size and malformed-response limits;
- normalized 429, 5xx, and provider-maintenance handling.

The existing `AuthRateLimitBucket` pattern is the starting shared authority:
keys are HMACed, raw IP/token values are not persisted, and the gate commits
before expensive password/provider work. A phone-specific policy must be
separate from email login limits and must be tested in PostgreSQL with multiple
workers.

The provider concurrency cap must not be only a process-local semaphore. Use a
reviewed shared lease/claim mechanism compatible with the deployment's database
authority, or explicitly document and test an equivalent multi-instance control.

## Retry Model

Provider retry policy is conservative because tokens are documented as
single-use and the official provider does not document an idempotent GetMobile
recovery API:

| Outcome | Backend action | Client action |
| --- | --- | --- |
| Local unavailable/privacy/capability failure | Do not call provider | Show email fallback. |
| User cancellation/switch method | No backend request required | Stay on auth surface/fallback. |
| Definitive invalid/expired/consumed token | Do not retry token | Request a fresh native token and new request id. |
| Provider 4xx with known non-retryable meaning | Do not retry token | Show provider-neutral error/fallback. |
| Provider 429/maintenance | Record normalized failure; bounded backoff only at JiYi gate | Retry only with policy permission and a fresh token if the token may be consumed. |
| Provider 5xx | Treat consumption as unknown unless the transport proves no request was sent; no automatic replay of the same token. | Obtain a fresh token/new request id after bounded backoff. |
| Network timeout/connection reset | `PROVIDER_UNKNOWN`/timeout receipt; no blind same-token GetMobile retry | Fresh token/new request id. Same request can safely query its existing receipt. |
| JiYi response lost after completed receipt | Do not call provider | Retry same request id; server reuses the recorded user/exchange outcome and issues a standard JiYi session according to policy. |

An implementation may retry an operation only when its transport layer proves
the request was never sent. That proof must be testable; an ordinary HTTP 5xx
or timeout is not proof.

## Error Contract

Stable JiYi errors, not Alibaba raw errors:

| Code | HTTP | Retryability | Client behavior |
| --- | ---: | --- | --- |
| `AUTH_PHONE_ONE_TAP_UNAVAILABLE` | 503 | No immediate same-token retry | Hide/disable one-tap and use email fallback. |
| `AUTH_PHONE_ONE_TAP_TOKEN_INVALID` | 401 | Fresh token required | Reopen native flow; do not resend token. |
| `AUTH_PHONE_ONE_TAP_TOKEN_EXPIRED` | 401 | Fresh token required | Reopen native flow. |
| `AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED` | 409 | No | Stop this exchange; fresh token/new request id. |
| `AUTH_PHONE_ONE_TAP_CONFLICT` | 409 | No | Stop and report a safe generic auth error; never overwrite ledger. |
| `AUTH_PHONE_ONE_TAP_TIMEOUT` | 504 | Same request only queries receipt; provider call not repeated | Fresh native token/new request id after bounded backoff. |
| `AUTH_PHONE_ONE_TAP_PROVIDER_ERROR` | 502 | Depends on normalized class; never infinite | Generic error/fallback; fresh token if retry allowed. |
| `AUTH_RATE_LIMITED` | 429 | After `Retry-After`; fresh token if token may be consumed | Respect backoff. |
| `AUTH_ACCOUNT_UNAVAILABLE` | 401 | No | Existing disabled-account behavior. |
| `ACCOUNT_DELETION_IN_PROGRESS` | Existing AUTH-01 semantics | Not a provider retry | Preserve continuation flag and existing 423 data fence. |

Native-only states `USER_CANCELLED` and `SWITCH_TO_OTHER_METHOD` normally do
not reach the backend. Raw Alibaba codes, AccessKey data, scheme keys, and
internal request details must never be returned to the client.

## Secrets / Configuration

Server-only material:

- Alibaba AccessKey ID/Secret, RAM role, STS material, or equivalent official
  server credential;
- server-side PNVS API client configuration and endpoint policy;
- token-fingerprint HMAC key and key-version metadata;
- provider concurrency and timeout configuration;
- any provider credential used to call GetMobile.

These must remain outside Flutter, APK, IPA, Git, ordinary logs, analytics,
crash reports, and client configuration responses.

The native SDK requires an Alibaba PNVS scheme key through `setAuthSDKInfo`.
Official documentation distinguishes that scheme key from AccessKey ID/Secret,
but the current official evidence does not establish a safe, JiYi-approved
delivery/classification model for the native key. Therefore:

- no scheme key is committed in AUTH-02A;
- no key is placed in Flutter or source-controlled build files;
- AUTH-02C must confirm the exact current SDK delivery requirement and rotate
  policy;
- AUTH-02E production binding is blocked until the reviewed client-safe versus
  server-only classification is documented.

The phrase “client-safe vendor config” must not be used to smuggle a scheme key
into a binary without this provider-specific review.

## Logging / Observability

Never log, persist, or emit:

- raw provider login token;
- full verified phone number;
- AccessKey ID/Secret or RAM token;
- PNVS scheme key;
- raw refresh token, access token, or authorization code;
- provider response bodies containing PII.

Allowed structured fields, subject to JiYi privacy retention policy:

- exchange id and request id;
- token fingerprint prefix only, never the raw token;
- provider request id;
- normalized JiYi outcome/error code;
- start/end/duration and timeout classification;
- carrier type only when needed and approved by privacy policy;
- hashed/masked phone only when operationally necessary and retained for the
  minimum reviewed period;
- app SHA/backend SHA, SDK version, platform, and capability reason.

The exchange ledger is an operational security record, not an identity
authority. PII retention, access control, purge, and audit must be specified in
AUTH-02B before production.

## Privacy / Authorization Page

The PNVS authorization page must be provider-native and user-driven:

- no simulated clicks or automatic confirmation;
- no bypass of carrier/provider terms;
- no fake number display or client assertion;
- explicit acceptance of JiYi privacy policy/user agreement and the provider
  authorization terms before the SDK may complete the exchange.

Before native initialization, JiYi must disclose PNVS in its privacy policy,
including the documented service purpose and the provider's collection of
network type, IP/device information, OS, and SIM state as applicable. The
official compliance guide requires app privacy consent before SDK
initialization. If JiYi privacy consent is absent, unknown, revoked, or the
provider disclosure has not been accepted in the reviewed consent model, the
capability is unavailable and no pre-login is allowed.

The provider authorization page remains the authority for carrier terms. JiYi
may configure reviewed links/text, but may not remove required provider
agreements or represent provider confirmation as JiYi confirmation.

## App Lifecycle

The bridge and backend contract must cover:

- double-tap login: one in-flight native operation per auth surface;
- authorization page open while app backgrounds and foregrounds;
- route disposal before native callback;
- native activity/view-controller recreation;
- user cancellation and switching methods;
- provider timeout and network transition;
- Wi-Fi/data network switch;
- SIM/data-card switch;
- JiYi session generation or account state changing during the callback;
- late callbacks after logout, account switch, or a new auth attempt.

Every operation receives an internal generation/request binding. A callback is
accepted only when its generation is still current, the auth surface is
mounted, and the session/account generation has not changed. Late callbacks
are discarded and cannot publish a token, error, or authenticated shell into a
new auth state. `dismiss()` and route disposal must cancel local presentation
ownership without assuming that a provider callback will not arrive.

With a valid JiYi session, app startup restores the existing session and must
not initialize or pre-login PNVS merely to refresh the shell.

## Test Matrix

AUTH-02B fake-provider/backend tests must cover:

- valid, malformed, invalid, expired, consumed, and provider-rejected token;
- provider timeout, 429, 5xx, maintenance, and malformed response;
- provider request id propagation and normalized error mapping;
- existing PHONE identity resolution;
- new PHONE identity creation and default entitlement;
- legacy `User.phone` projection without identity (must not log in that User);
- `auth_disabled_at` hard deny;
- known Account Delete continuation;
- unknown PHONE cannot enter deleting account;
- same token + same request retry;
- same token + different request replay;
- same request + different token conflict;
- response loss after provider success;
- provider-consumed token with unknown response;
- concurrent same-token reservation;
- concurrent first-ever same-phone login with different valid tokens;
- concurrent existing-phone login;
- provider I/O outside every User/identity/session critical transaction;
- durable behavior across process restart and multiple PostgreSQL workers;
- per-IP, per-device/install, request-id, and token-fingerprint abuse gates;
- provider concurrency cap and timeout;
- raw token absent from logs, ledger, analytics, and crash payloads.

AUTH-02C native tests must cover:

- availability and every unavailable prerequisite;
- prepare success/failure and bounded timeout;
- authorization page presentation and explicit consent;
- token acquisition and typed mapping;
- user cancel and switch method;
- provider timeout;
- double tap;
- background/foreground and native recreation;
- route disposal and late callback;
- network transition, SIM/data-card change, dual-SIM behavior;
- session-generation change during callback.

Existing AUTH-01, persistent-session, account-deletion, security, and
PostgreSQL integration tests remain regression gates; this phase does not alter
them.

## Real-device Acceptance

The success path must not be accepted on an emulator. Future AUTH-02E
acceptance must use physical iOS and Android devices and, where feasible,
separate real devices/SIMs for:

- China Mobile;
- China Unicom;
- China Telecom;
- 4G/5G cellular data;
- Wi-Fi plus active SIM;
- dual SIM with each tested default data card;
- no SIM;
- airplane mode;
- user cancellation;
- unavailable provider/capability;
- token timeout/response loss;
- network transition;
- repeated login tap.

Each run records device model, OS, carrier, data/Wi-Fi state, SIM layout,
app SHA, backend SHA, SDK version, scheme identifier (never the key), final
signing identity, request/exchange id, and normalized result.

## Implementation Phases

| Phase | Scope | Gate |
| --- | --- | --- |
| AUTH-02A | This provider/architecture/security specification and repository audit | Narrow review; no production code. |
| AUTH-02B | Provider-neutral backend adapter, fake provider, `/v1/auth/phone/one-tap`, durable exchange ledger, replay/idempotency, rate/concurrency controls, tests | Official TTL/retry gaps reconciled; no real credential required for fake-provider tests. |
| AUTH-02C | Android/iOS native PNVS adapters, provider-neutral bridge, capability and privacy gating | Native SDK version and scheme/key delivery reviewed; still not production-ready without final identities. |
| AUTH-02D | Auth V3 UI wiring to real capability/fallback | Separate UI scope; no visual-parity work in this phase. |
| AUTH-02E | Production scheme, final Android certificate, Apple registration, provider account/credentials, physical-device acceptance, operations/retention | Blocked by external identity/signing/provider prerequisites. |

AUTH-03 SMS OTP, AUTH-04 WeChat, push, and other providers are not hidden
subtasks of these phases.

## Resolved Questions

- Provider: Alibaba Cloud PNVS is selected for V1.
- Permanent phone provider: `AuthProvider.PHONE` remains the only one.
- One-tap identity: one-tap is only a verification method.
- Client phone authority: the client can never authenticate by submitting a
  phone number.
- Phone source: only server-side GetMobile output may become the phone subject.
- Raw token handling: no persistence, logging, analytics, crash storage,
  secure-storage storage, or database plaintext.
- Durable exchange: required; process memory alone is insufficient.
- External I/O: GetMobile is outside User/identity/session critical sections.
- Existing PHONE: resolve through AUTH-01.
- New PHONE: create through AUTH-01 atomic identity/User/entitlement creation.
- Legacy `User.phone`: no fallback login.
- Account deletion: retain AUTH-01 continuation semantics.
- `auth_disabled_at`: hard deny.
- Capability: fail closed.
- Android production scheme: wait for the final release certificate.
- Apple registration: remains externally unverified.
- Backend changes in AUTH-02A: none.
- Mobile/native changes in AUTH-02A: none.
- Real SDK in AUTH-02A: none.
- Provider secrets in AUTH-02A: none.
- SMS and WeChat in AUTH-02A: not started.

## Unresolved Questions

These are explicit implementation gates, not guesses:

- Exact current token TTL, especially the official 30-minute versus 60-minute
  China Unicom conflict.
- Exact provider guarantee for token/app/scheme binding and whether binding is
  cryptographic, configuration-only, or version-specific.
- Exact native scheme-key delivery/classification and rotation model. Official
  docs say the SDK consumes a scheme key and distinguish it from AccessKey
  credentials, but do not provide JiYi's reviewed delivery model here.
- Exact current Android/iOS SDK versions, architecture support, and upgrade
  requirements at the time of AUTH-02C download.
- Exact GetMobile retry/consumption behavior for each provider 4xx, 429, 5xx,
  timeout, and connection reset class.
- Whether any official provider receipt/query exists for an ambiguous GetMobile
  completion; current evidence does not establish one.
- Final JiYi ledger retention/purge duration and whether any encrypted PII is
  necessary; default is no clear-text phone in the ledger.
- Final distributed provider-concurrency lease mechanism and numeric caps.
- Final privacy-policy wording, consent storage authority, and carrier
  metadata retention.
- Final stable mapping for provider error taxonomy to the JiYi contract.

## External Blockers

Production binding and acceptance remain blocked until:

- final Android release signing certificate/key material is available and
  verified;
- Apple App ID/Bundle ID registration is externally verified;
- Google Play registration is externally verified;
- PNVS account billing/service activation is confirmed;
- production PNVS scheme is created for `com.jiyidays` and the final Android
  certificate/Apple Bundle ID;
- reviewed server-side GetMobile credential/RAM permission is provisioned;
- provider scheme-key delivery is reviewed and implemented without committing
  secrets;
- the real iOS/Android SDK versions are selected and accepted;
- physical devices and real SIMs for the carrier matrix are available;
- official token TTL/retry gaps are reconciled and encoded in tests;
- production privacy, terms, observability, retention, and incident response
  review is complete.

## Review Gate Answers

1. Provider locked to Aliyun PNVS: **yes**.
2. `PHONE` remains the only phone AuthProvider: **yes**.
3. `ONE_TAP` is only a verification method: **yes**.
4. Client cannot submit phone as authentication authority: **yes**.
5. Phone can only come from server-side GetMobile: **yes**.
6. Raw token persistence/logging is forbidden: **yes**.
7. Durable exchange/replay ledger required: **yes**.
8. Provider I/O is separated from DB critical transactions: **yes**.
9. Existing PHONE reuses AUTH-01 resolver: **yes**.
10. New PHONE reuses AUTH-01 atomic create: **yes**.
11. Legacy `User.phone` fallback login is forbidden: **yes**.
12. Account deletion continuation is preserved: **yes**.
13. `auth_disabled_at` is hard deny: **yes**.
14. Capability fails closed: **yes**.
15. Android production scheme waits for final release cert: **yes**.
16. Apple external registration remains unverified: **yes**.
17. Backend modified in AUTH-02A: **no**.
18. Mobile/native modified in AUTH-02A: **no**.
19. AUTH-03 SMS started: **no**.
20. AUTH-04 WeChat started: **no**.
21. Real SDK added: **no**.
22. Provider secret committed: **no**.

AUTH-02A is a specification checkpoint only. Do not begin AUTH-02B from this
document without the next explicit task.
