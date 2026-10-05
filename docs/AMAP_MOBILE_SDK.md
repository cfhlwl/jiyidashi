# JiYi AMap mobile rendering authority

UIUX-P0-002 uses the AMap native mobile map SDK through the explicitly reviewed Flutter compatibility bridge pinned for PR #205.

The preferred official Flutter package remains `amap_flutter_map 3.0.0`, but that release is not compatible with this repository's current Dart/Flutter/Android Gradle toolchain without maintaining a substantial local fork. The current bridge deviation, exact pub.dev archive checksum, risk assessment, and re-review triggers are documented in `docs/security/amap-flutter-bridge-supply-chain-review.md`. This is a reviewed exception, not a claim that the bridge is an official AMap package.

## Key separation

Never reuse the backend Web Service key in Flutter.

- Backend reverse geocoding / place naming: `AMAP_WEB_SERVICE_KEY` (server only)
- Android map rendering: `AMAP_ANDROID_SDK_KEY`
- iOS map rendering: `AMAP_IOS_SDK_KEY`

The mobile keys are supplied at build time with `--dart-define`. No real key, keystore, COS credential, or backend Web Service key is committed to this repository. CI uses obvious non-secret placeholder SDK keys only to prove the production startup gate is wired.

Production startup calls `JiYiAmapConfig.assertProductionConfiguration()` before `runApp`. Android/iOS production builds without the platform SDK key fail closed instead of shipping a green build whose maps can never initialize.

Current identifiers:

- Android applicationId: `cn.jiyidashi.jiyidashi`
- iOS Bundle ID: `cn.jiyidashi.jiyidashi`

Android release signing is not yet final. A production AMap Android key must be issued against the final release signing certificate before store release; do not bind production authority to the current debug signing configuration.

## Privacy boundary

The AMap native widget must not be constructed before the user has accepted the app privacy statement that includes the AMap map service disclosure.

The Flutter adapter therefore fails closed:

```text
privacy not accepted
-> no AMapWidget construction
-> factual place/time fallback only

privacy accepted + platform SDK key present
-> AMapWidget may initialize
-> real canonical Place coordinates only
```

Before the accepted branch is entered, JiYi presents an explicit AMap disclosure describing the provider, map purpose, server-owned place coordinates used for display, and the device/network information needed by the SDK. Persisted consent is written only after the user presses **同意并启用**.

The accepted bootstrap order is strict:

```text
show AMap disclosure
-> explicit user agreement
-> persist JiYi AMap consent
-> AMapInitializer.updatePrivacyAgree(hasContains/show/agree = true)
-> AMapInitializer.init(platform SDK key)
-> construct native AMapWidget
```

No AMap SDK initializer is called on the denied branch. Profile exposes a dedicated revoke action backed by the same shared consent authority. Revocation notifies active product surfaces and returns them to the factual non-map fallback before any future map construction.

## Location truth

Maps consume only canonical Day/Today/Place coordinates already projected by the backend. UIUX-P0-002 does not expose raw `LocationPoint` history.

Where more than one Visit is mappable, the UI may draw a visual connector in visit order. That connector is explicitly labeled as visit order and must never be described as the exact walked/driven/transit route.

No coordinate means no marker. Map failure never removes the factual place/time list.

## Local media

Photo presentation is local-first and owner scoped. Signed COS URLs remain short-lived download capabilities only and are never persistent cache keys.

Persistent cache identity is:

```text
owner_user_id
+ media_id
+ server-owned opaque cache_version
```

The `cache_version` is derived server-side from canonical READY media metadata and storage revision material, then hashed before projection so raw storage keys/ETags remain private.

Online cache hits are not treated as permanent authorization. They require a short in-process authority lease; after the lease expires JiYi revalidates the server download capability. If the server returns 403/404, the stale local media object and authority lease are invalidated immediately. Offline mode may still render bytes previously cached for the same authenticated owner, preserving the reviewed offline presentation behavior without creating cross-account authority. When an online authority revalidation fails specifically with a transport/connectivity error, JiYi may fall back to the already-cached bytes for that still-current owner; protocol failures and server 403/404 responses never use that fallback. Session identity is rechecked after asynchronous cache/network operations so an account switch cannot inherit the old owner's fallback.

Family photos use the viewer account as the cache owner and embed the resource owner's UUID in the media cache key. Family photo list/download reads remain server-authorized. A successful current Family Photos list read may authorize reuse of that viewer's cached bytes; a transport failure does not create or extend family-share authority. A 403/404 on Family Photos purges that resource owner's family-photo cache prefix for the viewer.

Account deletion purges that owner's presentation cache. Ordinary logout may retain private app-local cache according to product policy, but a different account can never resolve another owner's cache path.
