# JiYi App Identity — APP-ID-001

This repository freezes the production app identity as `com.jiyidays`.

| Surface | Frozen value |
| --- | --- |
| Android `applicationId` | `com.jiyidays` |
| Android namespace / Kotlin package | `com.jiyidays` |
| iOS Runner Bundle ID | `com.jiyidays` |
| iOS RunnerTests Bundle ID | `com.jiyidays.RunnerTests` |
| iOS passive recovery task | `com.jiyidays.passive-recovery` |

The historical Android/iOS identity `cn.jiyidashi.jiyidashi` and its package
path are not aliases of the new identity. Android sandbox data, Keystore,
SharedPreferences, and SQLite data do not automatically transfer between
these identities. The iOS Bundle ID likewise selects a new app container.
This test-stage migration intentionally performs **no automatic local data
migration**. A new install starts with the new identity; server-side restore
continues to use the existing account authority.

`User.id`, `AuthIdentity`, `AuthSession`, backend user data, Memory, Location,
Family, and Entitlement remain server-owned. App identity migration does not
create or migrate backend user IDs.

## Release signing

The repository contains no keystore or signing secret. Release signing is
configured only when all four inputs are supplied through environment
variables or Gradle properties:

- `ANDROID_RELEASE_KEYSTORE_PATH` / `android.release.storeFile`
- `ANDROID_RELEASE_KEYSTORE_PASSWORD` / `android.release.storePassword`
- `ANDROID_RELEASE_KEY_ALIAS` / `android.release.keyAlias`
- `ANDROID_RELEASE_KEY_PASSWORD` / `android.release.keyPassword`

With no key material, the release build is intentionally unsigned and reports
`ANDROID_RELEASE_SIGNING=INFRA READY / KEY MATERIAL PENDING`. It never falls
back to the debug key. A production signing gate is available with
`-PrequireProductionSigning=true`, which fails closed when the four inputs are
not complete. The CI no-secret validation runs
`verifyReleaseSigningConfiguration` before the unsigned release build.

## External registration status

Repository identity migration does not verify external portals:

```text
APPLE_APP_ID_REGISTRATION = NOT VERIFIED EXTERNALLY
GOOGLE_PLAY_ID_REGISTRATION = NOT VERIFIED EXTERNALLY
```

No Firebase configuration, Associated Domains, custom URL scheme, or APNs
entitlement is configured in this repository. Provider registration and SDK
integration remain later work and must use `com.jiyidays`.

The existing `cn.jiyidashi/...` Flutter MethodChannel names are stable
internal protocol identifiers and are deliberately preserved. They are not
Android application IDs and were not mechanically renamed.
