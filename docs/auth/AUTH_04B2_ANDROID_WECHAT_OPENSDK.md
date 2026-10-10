# AUTH-04B2 Android WeChat OpenSDK Native Login

## Status

`ANDROID CODE READY / FIELD BLOCKED` is the target for this phase. This document
records the Android bridge and the evidence used for the locked dependency. It
does not claim a WeChat AppID approval, release-signature registration, real
authorization success, or production enablement.

Production remains fail closed:

```text
AUTH_WECHAT_PROVIDER=disabled
JIYI_WECHAT_LIVE_ENABLED=false
JIYI_WECHAT_APP_ID=<empty>
```

No AppSecret is present in Android, Flutter, Git, or the APK/IPA configuration.

## Official evidence

Authority is limited to Tencent/WeChat official documentation:

- [Android 接入指南](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/Access_Guide/Android.html)
- [Android Open SDK 资源下载](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/Downloads/Android_Resource.html)
- [移动应用微信登录开发指南](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/WeChat_Login/Development_Guide.html)
- [微信 Open SDK 开发者合规使用指南](https://developers.weixin.qq.com/doc/oplatform/Mobile_App/agreement/sdk.html)
- [微信 Open SDK 个人信息处理规则](https://support.weixin.qq.com/cgi-bin/mmsupportacctnodeweb-bin/pages/RYiYJkLOrQwu0nb8)

The official Android guide states that the SDK moved from the old
`com.tencent.mm.sdk` package to `com.tencent.mm.opensdk`, and that Android
Studio projects should consume the Maven Central artifact
`com.tencent.mm.opensdk:wechat-sdk-android`. It also documents Android 11
package visibility and the need to declare the `com.tencent.mm` package in
`<queries>`.

The official resource page currently lists version `6.8.34` in its basic-info
field, while its version history lists `6.8.40` and the official Maven Central
coordinate resolves that exact AAR. This page inconsistency is recorded rather
than hidden. The implementation pins `6.8.40`, the highest version listed by
the official resource history at audit time; a future dependency update must
re-run this audit.

The official resource page identifies the developer as Shenzhen Tencent
Computer Systems Co., Ltd. The artifact metadata describes the published AAR
under the Apache License 2.0. The repository pins the artifact and does not
copy an unverified third-party JAR into `libs`.

## Official login contract

The official login guide requires an approved mobile application with an AppID
and AppSecret, and describes native authorization with `SendAuth.Req`:

- the scope is `snsapi_userinfo`;
- a caller-supplied `state` is returned and is intended to protect request
  association/CSRF;
- the user authorizes or cancels in the WeChat client;
- the short-lived `code` is exchanged by the server, not by Android;
- AppSecret is server-only and is never shipped to the client.

The callback owner is the official `wxapi.WXEntryActivity` route. The
implementation declares `com.jiyidays.wxapi.WXEntryActivity` as exported,
`singleTask`, and uses the frozen package identity `com.jiyidays`. Android
package visibility declares `com.tencent.mm`.

The official compliance guide requires the app to disclose the SDK in its
privacy policy and to initialize it only after the user has given consent. The
bridge therefore does not initialize, probe installation, or send an auth
request before `privacy_consent_granted=true`. Revocation invalidates the
request and clears the native adapter state.

## Native bridge contract

Flutter continues to use the existing
`MethodChannel('cn.jiyidashi/wechat_auth')` and
`WechatLoginCoordinator`. Android implements:

```text
initialize(privacy_consent_granted)
checkAvailability()
requestCredential()
cancel()
revokePrivacy()
```

The only successful credential payload is an in-memory, opaque WeChat `code`
under the provider-neutral Flutter key `credential`. The code is not logged,
persisted, copied to the clipboard, sent to analytics, or included in crash
details. It is passed to the existing server exchange contract only.

Native states are exactly the existing contract:
`AVAILABLE`, `UNAVAILABLE`, `CANCELLED`, `TIMEOUT`, `PROVIDER_ERROR`, and
`CREDENTIAL_ACQUIRED`.

The adapter is request-scoped and fail closed. It enforces:

- single-flight request state;
- cryptographically random request `state` and exact callback-state matching;
- callback generation fencing and duplicate/late callback rejection;
- explicit cancel, timeout, privacy revoke, engine detach, Activity detach,
  and application-background invalidation;
- no credential completion when WeChat is absent, unsupported, unconfigured,
  or the official SDK registration fails.

`WXEntryActivity` is only the official callback transport endpoint. It forwards
the typed error/state/code tuple to the active request registration and never
owns a session, controller, AppSecret, or durable credential store.

## Configuration and production gate

The Android build accepts only non-secret configuration seams:

```text
JIYI_WECHAT_APP_ID          client AppID, empty by default
AUTH_WECHAT_PROVIDER         disabled by default
JIYI_WECHAT_LIVE_ENABLED     false by default
```

Enabling live mode requires an explicit `AUTH_WECHAT_PROVIDER=wechat` and a
non-empty AppID; otherwise the Gradle configuration fails closed. This phase
does not provide those values and does not register an AppID or signing
fingerprint. No Android configuration can contain AppSecret.

The Flutter app now supplies the real MethodChannel gateway by default, while
tests may inject `FakeWechatAuthGateway`. The existing server capability,
native availability, and privacy gates remain the only authority for showing
the already-reviewed WeChat entry. Email and phone login paths are unchanged.

## Verification matrix

Automated native tests cover:

- privacy and missing-configuration fail closed before SDK access;
- missing WeChat installation;
- unsupported callback state and missing code;
- successful matching-state callback with one completion;
- duplicate, cancel, timeout, and late callback fencing;
- MethodChannel initialize/request/cancel result mapping;
- no raw-code diagnostic representation.

The repository-level gates remain required: Android debug/release builds,
Kotlin/Java native tests, Flutter WeChat/channel tests, backend and PostgreSQL
AUTH-04 tests, `backend-ci`, `production-deployment-ci`, `miniprogram-ci`,
`mobile-ci`, `mobile-visual-preview`, and `core004`. Existing visual/Golden
failures are not updated or reclassified by this phase.

## External blockers

The following are not solved by code in AUTH-04B2:

- approved WeChat mobile AppID and Android package/signature registration;
- final Android release certificate and its registered fingerprint;
- production Android device with WeChat installed for authorization acceptance;
- production privacy-policy publication and SDK disclosure review;
- real authorization/return-code exchange acceptance.

Therefore this phase cannot claim `WECHAT LIVE`, Android FIELD PASS, or a
production provider enablement.
