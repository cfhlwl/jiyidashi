# AUTH-002 WeChat Mini Program Identity

## Status

AUTH-002 implementation is provider-neutral and test-ready on the dedicated
branch. The live WeChat provider remains disabled and fail closed. No AppSecret,
live login, production deployment, or real-device acceptance is included in
this change.

## Authority and provider separation

The Mini Program provider is `WECHAT_MINIPROGRAM`; it is intentionally distinct
from the mobile App `WECHAT` provider. A successful exchange creates or resolves
only:

```text
AuthIdentity(provider=WECHAT_MINIPROGRAM,
            subject="openid:<server-configured-app-id>:<openid>")
```

`unionid` is accepted only as provider metadata and is never an automatic
identity-linking or account-merge authority. Existing `User.id`,
`AuthIdentity`, and the standard AUTH-01 session issuer remain the canonical
account and session authorities.

## Official provider contract

The client explicitly calls `wx.login()` and sends only the opaque one-time
`code`, a request ID, and installation metadata to JiYi. The backend calls the
official server-side endpoint:

```text
GET https://api.weixin.qq.com/sns/jscode2session
  ?appid=<server-only AppID>
  &secret=<server-only AppSecret>
  &js_code=<transient wx.login code>
  &grant_type=authorization_code
```

The response must contain `openid` and `session_key`; the adapter may read an
optional `unionid`. JiYi discards `session_key` immediately. It is never returned
to the client, persisted, logged, or included in analytics/crash data.

Official evidence:

- [wx.login(Object object)](https://developers.weixin.qq.com/miniprogram/dev/api/open-api/login/wx.login.html)
- [code2Session](https://developers.weixin.qq.com/miniprogram/dev/OpenApiDoc/user-login/code2Session.html)

The provider adapter is restricted to HTTPS, the official
`api.weixin.qq.com` host, port 443/default, and the fixed path above. Redirects,
credentials, query/fragment additions to the configured base URL, unexpected
paths, malformed JSON, oversized responses, and provider errors fail closed.

## Backend contract

`POST /v1/auth/wechat-mini/exchange` accepts:

```json
{
  "code": "opaque-transient-code",
  "request_id": "uuid",
  "device_id": "installation-id",
  "client_platform": "miniprogram",
  "device_name": "optional"
}
```

It rejects extra fields and does not accept `openid`, `unionid`, `phone`,
`session_key`, or a client-asserted user. A successful response is the existing
standard `TokenResponse`, issued by AUTH-01. The WeChat provider credential is
never a JiYi access or refresh token.

## Durable exchange and transaction boundary

`auth_wechat_miniprogram_exchanges` is the durable replay ledger. It stores only
a server-keyed HMAC fingerprint of `wx.login` code, request metadata, terminal
state, provider request metadata, and resolved JiYi references. It never stores
raw code or `session_key`.

The flow is:

```text
anonymous rate/concurrency gate
→ committed RESERVED receipt
→ database transaction released
→ one provider code2Session call
→ short identity/session transaction
→ COMPLETED receipt + standard TokenResponse
```

The provider call never runs while an identity or session critical section is
held. `COMPLETED` and `PROVIDER_REJECTED` receipts are terminal. A timeout,
transport error, malformed response, or unknown provider completion is recorded
as `PROVIDER_UNKNOWN`; the same code cannot be sent to WeChat again by a retry.

The same `request_id` with a different code is a conflict. The same code with a
different request ID is a replay. Concurrent reservations and the unique
`(provider, subject)` identity constraint are resolved by PostgreSQL authority;
at most one canonical User owns a Mini Program subject.

## Client capability and session fencing

`GET /v1/auth/capabilities` exposes a separate `wechat_miniprogram` status. The
default is `DISABLED`; configuration/provider construction failures produce
`UNAVAILABLE`, never a clickable success path. The Mini Program page shows the
explicit login action only when this capability is `AVAILABLE`.

The client calls `wx.login()` only after explicit user action. The opaque code is
memory-only, and the existing session parser/install path is used for the full
`TokenResponse`. Auth-attempt generation, session epoch, logout, account switch,
and late-response fences prevent an old login from installing a stale session.

## Configuration and production gate

The selector defaults to disabled:

```text
AUTH_WECHAT_MINIPROGRAM_PROVIDER=disabled
AUTH_WECHAT_MINIPROGRAM_LIVE_ENABLED=false
```

Production AppID, AppSecret, API endpoint, fingerprint secret, and rate/lease
values are server-only deployment inputs. A fake provider is available only in
non-production test/development seams. Missing or incomplete live configuration
does not fall back to fake behavior and cannot report `AVAILABLE`.

## Abuse and error handling

Mini Program login has separate IP, device, request, credential-fingerprint, and
provider-concurrency limits. Provider-neutral error codes include unavailable,
invalid/rejected code, replayed code, conflict, timeout, provider error, and
rate limited. Raw WeChat error payloads and credentials do not cross the API
boundary.

## Tests and acceptance

The implementation includes provider transport contract tests, disabled/live
fail-closed tests, endpoint/capability tests, Mini Program controlled login and
stale-response tests, migration checks, and a real PostgreSQL gate covering:

- same code concurrent reservation with exactly one provider call and one durable
  session;
- completed receipt replay without a second provider call;
- distinct Mini Program identities remaining isolated from mobile `WECHAT`;
- concurrent same-openid resolution constrained by the PostgreSQL unique identity
  authority;
- no orphan user, identity, entitlement, or session created by the losing race.

The required CI workflows must validate the exact pushed HEAD. This branch does
not claim live WeChat, AppID/AppSecret registration, production configuration,
or physical-device acceptance.

## Scope boundaries

AUTH-04 native WeChat login, AUTH-04C field acceptance, SMS, PNVS, UI V3, and
production provider activation are outside this change.
