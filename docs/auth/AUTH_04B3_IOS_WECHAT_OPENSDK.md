# AUTH-04B3 iOS WeChat OpenSDK Native Login

## Status

`SCAFFOLD READY / EXTERNAL CONFIG BLOCKED`.

This phase adds the iOS native bridge, the locked Flutter MethodChannel
contract, native lifecycle tests, and non-secret configuration seams. It does
not claim a production WeChat AppID, Universal Link, Apple signing
registration, physical-device authorization, or production enablement.

Production remains fail closed:

```text
AUTH_WECHAT_PROVIDER=disabled
JIYI_WECHAT_LIVE_ENABLED=false
JIYI_WECHAT_APP_ID=<empty>
JIYI_WECHAT_UNIVERSAL_LINK=<empty>
```

No AppSecret or other provider credential is present in the client, repository,
test fixtures, or build configuration.

## Baseline and scope

The implementation starts from the latest `origin/main` audited for this
phase. It reuses the merged AUTH-04B2 Flutter/native contract and does not
change the backend exchange protocol, Auth-01 identity authority, UIUX V3,
Golden fixtures, or AUTH-04C field acceptance.

In scope:

- iOS OpenSDK adapter behind the existing provider-neutral bridge;
- privacy-gated initialization and capability probing;
- request-scoped presentation host and callback-state fencing;
- URL and Universal Link callback forwarding through AppDelegate and
  SceneDelegate;
- native XCTest coverage for unavailable, cancel, timeout, privacy revoke,
  duplicate/late callback, lifecycle, and missing-host paths;
- non-secret build configuration validation and CocoaPods dependency wiring.

Out of scope: real AppID or Universal Link registration, AppSecret, production
signing/certificate registration, production provider activation, physical
device acceptance, backend changes, WeChat Pay, and AUTH-04C.

## Official provider evidence

Authority is limited to official Tencent/WeChat and Apple documentation:

- [WeChat iOS access guide](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/Access_Guide/iOS.html)
- [WeChat iOS SDK resources](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/Downloads/iOS_Resource.html)
- [WeChat OpenSDK compliance guide](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/Compliance_Guide.html)
- [Apple: Supporting Associated Domains](https://developer.apple.com/documentation/xcode/supporting-associated-domains)
- [Apple: Supporting Universal Links](https://developer.apple.com/documentation/xcode/supporting-universal-links-in-your-app)
- [Apple TN3155: Debugging Universal Links](https://developer.apple.com/documentation/technotes/tn3155-debugging-universal-links)

The Tencent iOS guide documents the native OpenSDK, CocoaPods distribution
through `WechatOpenSDK-XCFramework`, Universal Links for SDK versions that
support them, `WXApi.registerApp(_:universalLink:)`, the authorization request
with `snsapi_userinfo` and a caller-provided `state`, and URL/Universal Link
callback forwarding. It also documents the WeChat query schemes
`weixin`, `weixinULAPI`, and `weixinURLParamsAPI`.

The official resource page audited for this phase lists XCFramework version
`2.0.9`; the Podfile pins that version. This is an SDK dependency decision,
not proof that JiYi has completed AppID or production registration.

Apple requires an Associated Domains entitlement containing an
`applinks:<domain>` entry and a public HTTPS AASA file whose app identity
matches the Team ID and bundle ID. Those values are intentionally not added
until the external registration and signing authority are verified.

## Locked Flutter contract

The iOS adapter uses the exact contract already consumed by the Flutter
`WechatAuthGateway` and Android AUTH-04B2:

```text
channel: cn.jiyidashi/wechat_auth

initialize({privacy_consent_granted})
checkAvailability()
requestCredential()
cancel()
revokePrivacy()
```

The only domain states are `AVAILABLE`, `UNAVAILABLE`, `CANCELLED`, `TIMEOUT`,
`PROVIDER_ERROR`, and `CREDENTIAL_ACQUIRED`. SDK-specific error numbers are
translated to provider-neutral reasons and are not exposed as the Flutter
authority. The successful payload contains only the transient opaque provider
code; it is not a JiYi access token.

## Native implementation

`WechatAuthNativeBridge` owns one request at a time. It obtains the actual
presenting `UIViewController` through the Flutter plugin registrar at request
time; it does not walk application windows, cache a permanent controller, or
guess a root controller. The request freezes a random callback `state`, a
generation, a timeout, and its completion. A callback is accepted only when
the state and generation still match the active request.

The bridge forwards both URL and Universal Link callbacks through the current
AppDelegate/SceneDelegate lifecycle paths. A normal external WeChat handoff
does not treat the first transition as an application-background cancellation;
after the app returns, a later genuine background event cancels the pending
request. Privacy revoke, engine detach, timeout, explicit cancel, and stale or
duplicate callbacks are fail-closed and complete at most once.

## Privacy and production configuration

No SDK registration, installation probe, authorization request, or callback
processing is available before current privacy consent. Revocation invalidates
the pending request and prevents a late code from reaching Flutter.

The client reads only non-secret configuration seams:

```text
AUTH_WECHAT_PROVIDER
JIYI_WECHAT_LIVE_ENABLED
JIYI_WECHAT_APP_ID
JIYI_WECHAT_UNIVERSAL_LINK
```

Unresolved build placeholders, empty values, disabled provider state, a
non-HTTPS Universal Link, a URL with query/fragment, or missing host fail
closed. The production build must never silently fall back to a demo AppID,
scheme, or link. AppSecret stays server-side and is not part of this phase.

The current repository does not contain verified AppID, Universal Link,
Associated Domains, Apple Team/signing registration, or AASA material. The
implementation therefore cannot report `AVAILABLE` in production.

## Tests and acceptance gates

The new iOS native tests cover:

- privacy=false and missing configuration before any SDK operation;
- registration and provider-neutral availability mapping;
- matching callback state with one in-memory credential completion;
- wrong-state, duplicate, and late callback fencing;
- explicit cancellation and timeout seams;
- privacy revoke with late callback rejection;
- missing presenter fail-closed behavior;
- external-handoff background suppression followed by real background
  cancellation.

The full phase still requires exact-HEAD execution of:

1. `mobile-ci`;
2. `mobile-visual-preview`;
3. `core004-ios-trollstore-fix`;
4. `ios-unsigned-ipa`;
5. `miniprogram-ci`;
6. `backend-ci` with the exact target SHA;
7. `production-deployment-ci` with the exact target SHA and verified base SHA.

Windows cannot execute Xcode, CocoaPods, or iOS native tests. Until the macOS
workflow runs and verifies the pinned SDK/API surface, this document does not
claim iOS code-ready or field-ready status.

## External blockers

- official WeChat AppID and iOS application registration;
- verified `com.jiyidays` iOS Bundle ID mapping;
- verified Universal Link domain and wildcard path;
- Apple Team ID, signing identity, Associated Domains entitlement, and AASA;
- physical iOS device with WeChat installed for authorization acceptance;
- privacy-policy and SDK disclosure review;
- independent macOS build/test evidence for the pinned SDK 2.0.9;
- production enablement approval and server-side credential provisioning.

Until these are resolved, AUTH-04B3 is a tested native integration scaffold,
not a production WeChat login activation. AUTH-04C remains out of scope.
