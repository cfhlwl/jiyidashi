# JiYi AMap mobile rendering authority

UIUX-P0-002 uses the AMap native mobile map SDK through the official Flutter map plugin path.

## Key separation

Never reuse the backend Web Service key in Flutter.

- Backend reverse geocoding / place naming: `AMAP_WEB_SERVICE_KEY` (server only)
- Android map rendering: `AMAP_ANDROID_SDK_KEY`
- iOS map rendering: `AMAP_IOS_SDK_KEY`

The mobile keys are supplied at build time with `--dart-define`. No key, keystore, COS credential, or backend Web Service key is committed to this repository.

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

The map plugin privacy statement is passed only on the accepted branch with:

- `hasContains = true`
- `hasShow = true`
- `hasAgree = true`

Revoking the app's map/privacy consent must return the product to the non-map factual fallback before any future map initialization.

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

Account deletion purges that owner's presentation cache. Ordinary logout may retain encrypted/private app-local cache according to product policy, but a different account can never resolve another owner's cache path.
