# AUTH-04B1 WeChat Server OAuth Adapter

## Status

`SERVER CODE READY / NATIVE SDK + FIELD PENDING`

This document covers only the server-side adapter for the WeChat Open Platform
mobile-app authorization-code exchange. It does not enable production WeChat
login, install Android/iOS OpenSDKs, configure callbacks, or perform field
acceptance.

The implementation starts from the merged AUTH-04A main:

`dc5f0f8a26fbebfd8237689cbcd8f358cbb5d7f0`

AUTH-04A's receipt, replay, identity, session, deletion, and disabled-account
authority remain unchanged. The adapter is consumed through the existing
`exchange_wechat_credential()` service only.

## Official provider evidence

Authority:

- [WeChat Open Platform mobile-app WeChat Login Development Guide](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/WeChat_Login/Development_Guide.html)
- [WeChat Open Platform mobile-app iOS access guide](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/Access_Guide/iOS.html)
- [WeChat Open Platform mobile-app Android access guide](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/Access_Guide/Android.html)
- [WeChat Open Platform mobile-app compliance guide](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/Compliance_Guide.html)

The official mobile guide defines the `authorization_code` flow: the native
client obtains a temporary `code`, and the server calls:

```text
GET https://api.weixin.qq.com/sns/oauth2/access_token
    ?appid=APPID
    &secret=SECRET
    &code=CODE
    &grant_type=authorization_code
```

The documented success response contains `access_token`, `expires_in`,
`refresh_token`, `openid`, `scope`, and optionally `unionid`. `unionid` is
accepted as optional because the official response only supplies it when the
required user-info authorization relationship exists. JiYi never uses the
provider access or refresh token as an application session.

The official guide also states that the temporary code is short-lived and
single-use. JiYi therefore treats transport timeouts, read failures, and HTTP
5xx responses as ambiguous completion: the receipt becomes terminal/unknown
through the existing service semantics and the adapter never retries.

## Adapter boundary

```text
opaque native code
        |
        v
WechatOAuthProvider
  fixed HTTPS host + bounded request
  response schema and app binding validation
        |
        v
VerifiedWechatResult(openid?, unionid?, verified_at)
        |
        v
existing AUTH-04A receipt / identity / session pipeline
```

The provider implementation is `WechatOAuthProvider`. Its transport is an
`httpx.MockTransport` seam in tests; production uses a single bounded HTTP
request. No business service imports HTTP response types or provider payload
types.

The result contains only the verified app binding, configured JiYi subject
scope, OpenID, optional UnionID, verification time, and an optional provider
request identifier. It does not contain `access_token`, `refresh_token`,
AppSecret, or the raw provider body.

## Endpoint and transport security

The adapter accepts only:

- scheme `https`;
- host `api.weixin.qq.com`;
- no credentials, non-default port, path, query, or fragment in the base URL;
- path `/sns/oauth2/access_token` selected by code, never by request input;
- `follow_redirects=False`;
- bounded connection/read timeout plus a hard end-to-end request budget;
- bounded response body (`AUTH_WECHAT_MAX_RESPONSE_BYTES`, default 65536);
- no automatic retry.

HTTP 3xx is rejected and never followed. HTTP 401 and other non-success
responses are normalized to provider-neutral failure. HTTP 429 is normalized
to `RATE_LIMITED`. HTTP 5xx, connect errors, read errors, and timeout errors
are ambiguous and normalized to `TIMEOUT` with no retry. Malformed JSON,
unexpected JSON types, missing access token/OpenID, invalid optional fields, and
AppID mismatch fail closed as `PROVIDER_ERROR`.

The adapter sends the configured AppID, server-only AppSecret, opaque code, and
fixed grant type. It does not accept an endpoint, AppID, OpenID, UnionID, or
profile field from the client request.

HTTPX/httpcore request records remain enabled for normal operational
observability. A permanently installed, context-aware output filter redacts
the AppSecret and authorization code from request messages, URL-encoded query
values, typed HTTPX URL/request/response values, nested structured `extra`
fields, exception objects, `exc_info`, and `stack_info`; typed telemetry
objects are converted to redacted text before a later formatter can call their
`str`/`repr`. It does not add or remove mutable logger filters per request.
Provider transport exceptions are converted without preserving the raw
exception as a cause, so neither INFO / DEBUG request logs nor error traces
contain the outbound query values. The whole request, including
response-header and streamed-body wait time, is bounded by the configured
end-to-end budget for the production `AsyncClient` transport and other
cooperative async transports. Cancellation closes the transport instead of
leaving a daemon worker behind. JiYi does not claim to forcibly terminate an
arbitrary synchronous/blocking custom transport; such a transport is outside
the production adapter contract and is not used by the supported transport
seam. If the budget expires, the provider result is discarded and the
existing receipt remains an ambiguous terminal failure; it cannot create a
session or trigger a second provider exchange.

## Provider error mapping

Known provider response codes are mapped without exposing `errmsg`:

| WeChat response | Internal adapter code | JiYi public result |
| --- | --- | --- |
| `40029` | `INVALID` | `AUTH_WECHAT_CREDENTIAL_INVALID` |
| `40163` | `REPLAYED` | `AUTH_WECHAT_CREDENTIAL_REPLAYED` |
| `45011` or HTTP 429 | `RATE_LIMITED` | `AUTH_RATE_LIMITED` |
| HTTP 5xx / network timeout | `TIMEOUT`, ambiguous | `AUTH_WECHAT_TIMEOUT` |
| other error or invalid schema | `PROVIDER_ERROR` | `AUTH_WECHAT_PROVIDER_ERROR` |

The existing receipt service records the provider outcome and prevents a
second provider call for the same credential/request reservation. A response
loss is therefore not repaired by calling WeChat again or issuing a second
JiYi session.

## Configuration and live gate

The following settings are server-only:

```text
AUTH_WECHAT_PROVIDER=disabled
AUTH_WECHAT_LIVE_ENABLED=false
AUTH_WECHAT_APP_ID=
AUTH_WECHAT_APP_SECRET=
AUTH_WECHAT_SUBJECT_SCOPE=
AUTH_WECHAT_API_BASE_URL=https://api.weixin.qq.com
AUTH_WECHAT_FINGERPRINT_SECRET=
AUTH_WECHAT_FINGERPRINT_KEY_VERSION=v1
AUTH_WECHAT_TIMEOUT_SECONDS=5
AUTH_WECHAT_MAX_RESPONSE_BYTES=65536
```

The default provider and live gate are both disabled. Production fake providers
are rejected. The factory reports the live adapter as available only when:

1. `AUTH_WECHAT_PROVIDER=wechat`;
2. `AUTH_WECHAT_LIVE_ENABLED=true`;
3. AppID, AppSecret, subject scope, fingerprint secret, and the fixed HTTPS
   endpoint are present and valid.

The actual exchange service still requires the existing fingerprint secret and
receipt controls. Missing or malformed configuration remains unavailable; it
does not silently select the fake provider or a test endpoint.

AppSecret and fingerprint secret must be injected by a server environment or
secret manager. They must not enter Git, Flutter, Android/iOS bundles, request
logs, analytics, crash reports, APM spans, or provider error text. This PR
contains no real secret and does not turn the live gate on.

## Logging and sensitive-data policy

Permitted operational fields are request/exchange ID, normalized outcome,
duration, deployment SHA, and adapter version. The following are prohibited:

- raw native `code`;
- AppID secret or fingerprint secret;
- provider access or refresh token;
- OpenID or UnionID;
- complete provider URL/query/body;
- raw `errmsg` or exception text.

The adapter sanitizes exceptions to `WechatProviderError` codes. HTTP clients
are created with redirects disabled and environment proxy settings disabled;
there is no adapter retry, and timeout cancellation does not leave a provider
exchange worker or connection task running after the call returns.

## Test evidence required for B1

The automated adapter suite uses `httpx.MockTransport` and proves:

- successful OpenID + UnionID exchange and OpenID-only exchange;
- AppID binding and response schema rejection;
- provider error-code normalization;
- HTTP 401, 429, 5xx and redirect rejection;
- no redirect to another host;
- response-size limit;
- timeout/connection ambiguity and no retry;
- INFO/DEBUG, exception-stack, structured-extra, URL-encoding, and concurrent
  credential log redaction;
- slow headers, slow bodies, continuous trickle bodies, and repeated
  cancellation-cooperative timeout runs with measured sub-budget return and no
  residual exchange workers;
- raw code, secret, tokens, and provider body are absent from surfaced errors;
- production/default/fake factory gating;
- the existing durable receipt blocks a second provider call when a completed
  exchange is replayed with the same code/request.

The existing PostgreSQL AUTH-04 gate remains authoritative for identity/session
concurrency, including shared-OpenID unique-constraint races and terminal
failure receipts. No migration or native SDK is introduced here.

## External blockers and later phases

Still blocked externally:

- approved WeChat Open Platform mobile AppID/AppSecret;
- production Android package/signing registration;
- production iOS Bundle ID/Universal Link and signing registration;
- reviewed native OpenSDK versions and callback wiring;
- real WeChat-installed Android/iOS devices;
- field acceptance for consent, cancel, missing client, timeout, background,
  replay, cross-device identity, and rollback.

AUTH-04B2 owns Android native SDK integration. AUTH-04B3 owns iOS native SDK
integration. AUTH-04C owns field acceptance. Until those phases pass
independent review, the correct state is `SERVER CODE READY / NATIVE SDK +
FIELD PENDING`, not `WECHAT LOGIN LIVE` or `AUTH-04 COMPLETE`.
