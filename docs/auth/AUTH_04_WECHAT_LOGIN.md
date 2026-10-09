# AUTH-04 WeChat Login Phase A

## Status

`CODE READY / WECHAT FIELD PENDING`

This phase adds the provider-neutral authority and test seams for native WeChat
login. It does not claim that a real WeChat Open Platform application, native
SDK, AppID/AppSecret, signing identity, or physical-device flow is ready.
Production capability remains fail closed while `AUTH_WECHAT_PROVIDER=disabled`.
AUTH-03P-B remains `CODE MERGED / FIELD PENDING`; this document does not enable
real SMS delivery.

## Baseline and scope

The implementation starts from the merged AUTH-03P-B main:

`348d565d24a1779b7d5b08fc92f0c590b6f90ba1`

In scope:

- provider-neutral WeChat credential exchange and durable replay receipt;
- scoped WeChat identity resolution through the frozen AUTH-01 authority;
- server-owned `wechat` capability status;
- provider-neutral Flutter/native gateway and fail-closed UI gating;
- backend, Flutter, and migration tests for the above.

Out of scope: real OpenSDK installation, AppID registration, AppSecret
activation, production scheme/universal-link wiring, field acceptance, SMS
activation, AUTH-05 identity merge, WeChat Pay, and UIUX-V3 visual work.

## Official Provider Evidence

Authority used for the scope decision:

- [WeChat Open Platform mobile-app WeChat Login Development Guide](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/WeChat_Login/Development_Guide.html)
- [WeChat Open Platform mobile-app post-authorization API / UnionID guide](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/WeChat_Login/Authorized_API_call_UnionID.html)
- [WeChat Open Platform iOS access guide](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/Access_Guide/iOS.html)
- [WeChat Open Platform Android access guide](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/Access_Guide/Android.html)
- [WeChat Open Platform OpenSDK compliance guide](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/Compliance_Guide.html)

The current official mobile-login guide establishes these facts used here:

1. Mobile login is an OAuth 2.0 authorization-code flow. The native SDK asks
   the user to authorize, returns a temporary `code`, and the server exchanges
   it with the AppID and AppSecret for provider identifiers.
2. Mobile login is a native flow and requires the WeChat client. The official
   guidance distinguishes Android and iOS availability handling; iOS should
   check whether the WeChat client is installed before showing the action.
3. The documented mobile scope is `snsapi_userinfo`. The returned `openid` is
   an identifier in the configured application context. `unionid`, when
   returned, is the cross-application identifier for applications in the same
   Open Platform account/group and must not be assumed for unrelated apps.
4. The native callback includes a provider `state` round trip and user outcome
   codes. JiYi treats that as callback correlation and user-consent state, not
   as an identity claim.

The official documentation does not make JiYi's exact alias migration policy,
provider retry completion semantics, or our durable receipt semantics. Those
are JiYi rules below. If a later SDK/API version changes scope or response
requirements, the live adapter remains unavailable until this contract is
re-reviewed.

## Locked AUTH-01 authority

`AuthProvider.WECHAT` remains the only WeChat identity provider. There is no
`AuthProvider.WECHAT_NATIVE`, `AuthProvider.OPENID`, or `AuthProvider.UNIONID`.

`AuthIdentity(provider, subject)` resolves to the canonical `User.id`, and the
existing `issue_authenticated_session()` boundary issues JiYi sessions. A
provider credential never becomes a JiYi bearer token.

The subject is always scoped and serialized as one of:

```text
unionid:<reviewed-open-platform-scope>:<unionid>
openid:<wechat-app-id>:<openid>
```

Bare `openid`, bare `unionid`, nickname, avatar, country, provider code,
access token, refresh token, UI text, and callback state are invalid identity
subjects. Subject components are validated by the existing
`canonicalize_wechat_subject()` authority.

When both identifiers are verified in one result, the UnionID subject is the
primary lookup subject and the application-scoped OpenID is an additive alias.
The alias is added only to the same resolved user. Existing aliases that point
to different users produce `AUTH_IDENTITY_CONFLICT` / `MERGE_REQUIRED`; no
automatic merge, owner transfer, or profile lookup is attempted. AUTH-05 owns
any explicit merge/link workflow.

## Server contract

`POST /v1/auth/wechat/exchange`

Request:

```json
{
  "credential": "opaque-native-provider-code",
  "request_id": "uuid",
  "device_id": "installation-id",
  "client_platform": "flutter",
  "device_name": "optional"
}
```

`credential` is opaque and transient. The request has no `phone`, `openid`,
`unionid`, nickname, or profile authority field. The server-side provider
adapter validates the credential and returns a structured verified result:

```text
app_id, reviewed scope, openid?, unionid?, verified_at, provider_request_id?
```

Success returns the existing `TokenResponse`, including
`account_deletion_in_progress`. Existing refresh rotation, logout, logout-all,
session-generation, device binding, and deletion-continuation rules remain the
session authority.

## Provider adapter

`WechatAuthProvider.exchange_credential()` is the only provider boundary.
`VerifiedWechatResult` carries verified provider identifiers only in memory and
normalizes them into scoped JiYi subjects. The business service does not import
OpenSDK/API types and never performs controller or profile lookup.

Phase A contains:

- `DisabledWechatAuthProvider`, the production-safe default;
- `FakeWechatAuthProvider`, an explicit test-only seam that is never exposed as
  a production capability;
- no real HTTP/OpenSDK adapter and no provider credential.

## Capability authority

`GET /v1/auth/capabilities` remains the single server capability surface. The
server returns `wechat=AVAILABLE` only when a reviewed live provider factory
reports readiness. Disabled, malformed, missing, or failed configuration is
`DISABLED`/`UNAVAILABLE`; neither is actionable.

Flutter reuses `AuthCapabilityAuthority`. A WeChat entry requires all of:

1. privacy consent is currently granted;
2. server `WECHAT=AVAILABLE`;
3. the local `WechatAuthGateway` is present and reports `AVAILABLE`.

Privacy false is Email-only: no WeChat SDK initialization, availability probe,
provider request, credential exchange, or identity creation occurs. Revocation
immediately hides WeChat, invalidates unauthenticated auth generation, cancels
the native request best effort, and rejects late callbacks/responses.

The Flutter production wiring currently supplies no live gateway, so WeChat is
hidden. A fake gateway can be injected by tests only.

## Native bridge contract

`WechatAuthGateway` is provider-neutral and maps native results to:

`AVAILABLE`, `UNAVAILABLE`, `CANCELLED`, `TIMEOUT`, `PROVIDER_ERROR`, and
`CREDENTIAL_ACQUIRED`.

The MethodChannel name is `cn.jiyidashi/wechat_auth`; raw SDK error codes are
not part of the Flutter domain. A credential is kept only in the bounded
in-memory attempt object until the exchange finishes. It is excluded from
`toString`, persistence, analytics, and error text.

Android and iOS must implement the same contract when their respective AppID,
SDK, signing, callback, and platform approval prerequisites are available.
Until then the native adapter must report unavailable. No global activity,
root view controller, or guessed callback host is an authority.

## Exchange receipt and replay

`auth_wechat_login_exchanges` is the durable PostgreSQL-compatible receipt. It
stores a server-keyed HMAC-SHA256 credential fingerprint, request ID, frozen
device identity, state, verified subject, provider request ID, session/user
references, lease, and bounded recovery fields. It never stores the raw code,
access token, refresh token, AppSecret, or provider response.

Rules:

- same credential fingerprint + same request ID: one provider call; a completed
  receipt permits one bounded replacement-session recovery;
- same credential fingerprint + different request ID: `AUTH_WECHAT_CREDENTIAL_REPLAYED`;
- same request ID + different credential fingerprint: `AUTH_WECHAT_CONFLICT`;
- provider I/O occurs after the reservation commit and before the short identity
  and session transaction;
- completed response loss recovers against the receipt's frozen `device_id`,
  never retry payload identity;
- the original session is revoked and the replacement session is issued under
  the same User/device/session authority ordering;
- recovery is single-use and bounded by the durable deadline/count.

## Transaction and concurrency rules

The service follows:

```text
anonymous rate gate
  -> durable reservation
  -> provider I/O (no DB critical transaction)
  -> short identity resolution/alias transaction
  -> shared session issuance
```

The provider cannot run while a User `FOR UPDATE`, identity critical section,
or session critical transaction is held. Existing identity conflicts are hard
errors. First-login races rely on the existing unique `(provider, subject)`
authority and return the winning User rather than creating or merging a second
account. Existing identity login reuses the same User. Disabled accounts remain
`AUTH_ACCOUNT_UNAVAILABLE`, even when provider verification succeeds. Active
account deletion keeps the existing continuation-session semantics; unknown
WeChat subjects cannot be inferred from profile projections.

## Error and privacy contract

The stable JiYi surface is provider-neutral:

`AUTH_WECHAT_UNAVAILABLE`, `AUTH_WECHAT_CREDENTIAL_INVALID`,
`AUTH_WECHAT_CREDENTIAL_EXPIRED`, `AUTH_WECHAT_CREDENTIAL_REPLAYED`,
`AUTH_WECHAT_CONFLICT`, `AUTH_WECHAT_TIMEOUT`, `AUTH_WECHAT_PROVIDER_ERROR`,
`AUTH_IDENTITY_CONFLICT`, and `MERGE_REQUIRED` where applicable.

The client receives no raw SDK code, URL, stack, AppSecret, access token,
OpenID, UnionID, or provider response. Cancellation is local
`CANCELLED`; it normally does not create a backend request. Provider failures
do not create a session and Email remains available.

Logs may contain only request/exchange ID, normalized outcome, duration, app and
backend SHA, SDK version, and permitted device/OS/carrier categories. Raw
credential, raw phone number, secret material, and complete provider response
are prohibited.

## Configuration and secrets

The server-only settings seam is:

```text
AUTH_WECHAT_PROVIDER
AUTH_WECHAT_APP_ID
AUTH_WECHAT_APP_SECRET
AUTH_WECHAT_SUBJECT_SCOPE
AUTH_WECHAT_API_BASE_URL
AUTH_WECHAT_FINGERPRINT_SECRET
AUTH_WECHAT_FINGERPRINT_KEY_VERSION
```

`AUTH_WECHAT_APP_SECRET` and the fingerprint secret must arrive through a
server environment or secret manager. They must not enter Flutter, APK, IPA,
Git, analytics, crash reports, or ordinary logs. AppID may be public client
configuration only after an approved production seam exists; Phase A does not
hardcode it. Missing or malformed required configuration fails closed.

## Lifecycle, cancellation, and rollback

The gateway must single-flight the request and fence duplicate taps, route
disposal, background/foreground transitions, native recreation, user cancel,
privacy revoke, account switch, and session-generation changes. A late callback
is accepted only for the still-current request generation. A late server
response cannot persist a session after the generation or privacy authority has
been invalidated.

Rollback is safe because Phase A does not install a real SDK or production
provider. Disabling the server provider returns `UNAVAILABLE`/`DISABLED`, and
removing the test gateway hides the client action without changing AUTH-01
identities or existing Email/Phone/SMS behavior.

## Test coverage

Backend tests cover scoped UnionID/OpenID alias resolution, bare/cross-user
conflict rejection, one-provider-call response-loss recovery, frozen device
identity, credential replay, capability neutrality, and absence of raw
provider values from the HTTP response. Flutter tests cover privacy-false
first-frame hiding/no probe, provider-neutral transient credential handling,
and late credential after privacy revoke.

PostgreSQL integration must additionally cover concurrent first login, existing
identity login, alias conflict, disabled account, deletion continuation,
same-request retry, different-request replay, and provider-I/O transaction
separation before field activation.

## Field prerequisites

### Android

- reviewed WeChat Open Platform mobile application and login capability;
- final `com.jiyidays` package and release signing certificate registered in the
  WeChat application;
- OpenSDK dependency and callback wiring reviewed for the actual release
  signing identity;
- physical WeChat-installed device acceptance for callback, cancel, background,
  and unavailable states.

### iOS

- reviewed WeChat Open Platform mobile application and login capability;
- `com.jiyidays` Bundle ID, Apple Team/signing identity, and any required
  Universal Link/callback configuration registered and verified;
- OpenSDK compliance/privacy review and physical-device acceptance;
- WeChat client-installed and client-absent behavior tested.

### Shared / server

- AppID/AppSecret activation and server secret-manager delivery;
- reviewed provider endpoint, timeout, retry, and unknown-completion semantics;
- provider account/approval state and operational quota/billing confirmation;
- carrier-independent real-device matrix where applicable.

Until all external prerequisites are verified, the status is
`CODE READY / WECHAT FIELD PENDING`, never `AUTH-04 DONE`.
