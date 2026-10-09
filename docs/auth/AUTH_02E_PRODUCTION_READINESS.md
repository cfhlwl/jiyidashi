# AUTH-02E Production Readiness / External Prerequisite Preflight

## Status

`CODE READY / EXTERNAL BLOCKED`

This document records the first AUTH-02E preflight. It does not activate Alibaba
Cloud PNVS, add a provider SDK, or provide any credential. The current native and
backend providers remain fail closed.

## Authority and secret boundary

The production authority remains:

```text
native provider SDK -> opaque login token -> Flutter transient value
-> JiYi backend -> server-side GetMobile -> canonical PHONE identity
-> existing JiYi session authority
```

The client never submits a phone number as login authority, decodes a phone
number, or persists a provider token. Alibaba server credentials belong only in
server environment/secret-manager delivery. They must not enter Flutter, APK,
IPA, Git, or logs.

## Android prerequisite matrix

| Item | Current result | Evidence / next gate |
|---|---|---|
| applicationId / namespace | READY | `com.jiyidays` is frozen in Gradle and APP-ID-001 |
| release signing configuration seam | READY | four server/CI inputs; no debug-key fallback |
| release certificate derivation gate | READY | production gate derives SHA-256 from the supplied keystore with `keytool` and compares it to the expected fingerprint |
| final release certificate fingerprint | EXTERNAL BLOCKED | must be generated from the final release keystore and registered with PNVS |
| PNVS scheme / app identifier | EXTERNAL BLOCKED | `JIYI_PNVS_SCHEME_ID` is an injected client-config seam; no value is committed |
| PNVS SDK | EXTERNAL BLOCKED | no Aliyun AAR is present or enabled |
| package + certificate binding | EXTERNAL BLOCKED | verify in PNVS console after final signing certificate exists |
| carrier/device acceptance | EXTERNAL BLOCKED | physical mainland SIM/device runs are pending |

Production enforcement is explicit: `requireProductionPhoneOneTap=true` requires
the scheme identifier and complete release signing inputs. Missing input fails the
Gradle configuration/build gate; it does not fall back to a demo scheme.
The Python preflight uses the same generic `JIYI_PNVS_SCHEME_ID` consumed by the
Android and iOS build seams; platform-specific scheme aliases are not accepted.
The release certificate fingerprint is derived from the actual configured
keystore and alias. A malformed or mismatched expected fingerprint fails closed,
and keystore passwords are passed to `keytool` through subprocess environment
variables rather than printed or embedded in command output.

## iOS prerequisite matrix

| Item | Current result | Evidence / next gate |
|---|---|---|
| Runner Bundle ID | READY | `com.jiyidays` in the Xcode project |
| signing/team identity | CODE READY / EXTERNAL BLOCKED | Release `DEVELOPMENT_TEAM` is bound to `JIYI_APPLE_DEVELOPMENT_TEAM`; Apple team/signing registration is not externally verified |
| PNVS application/scheme registration | EXTERNAL BLOCKED | `JIYI_PNVS_SCHEME_ID` is an injected xcconfig seam; no value is committed |
| PNVS SDK | EXTERNAL BLOCKED | no Aliyun framework/package is present or enabled |
| required provider capability/privacy review | EXTERNAL BLOCKED | official provider registration and privacy review remain pending |
| physical-device acceptance | EXTERNAL BLOCKED | iOS real-device carrier runs are pending |

The iOS bridge treats missing or placeholder configuration as unavailable. A
configured identifier alone still does not enable the provider adapter.
Release builds also run `mobile/tool/verify_auth_02e_ios_release_config.py` from
an Xcode build phase. When
`JIYI_PHONE_ONE_TAP_PRODUCTION_REQUIRED=YES`, the build fails closed unless the
build-consumed Bundle ID, PNVS scheme identifier, `DEVELOPMENT_TEAM`, and the
expected `JIYI_APPLE_DEVELOPMENT_TEAM` all match. CI tests this with synthetic
values only; it is not an Apple registration or PNVS readiness claim.

## Backend credential matrix

| Item | Current result | Evidence / next gate |
|---|---|---|
| provider-neutral adapter seam | READY | `PhoneOneTapProvider` remains the only backend boundary |
| real PNVS adapter | NOT READY | factory still returns disabled provider |
| AccessKey ID / Secret | NOT CONFIGURED | no value exists in repository or CI |
| RAM identity / secret-manager delivery | EXTERNAL BLOCKED | deployment contract must be selected before live activation |
| GetMobile endpoint / timeout / retry policy | EXTERNAL BLOCKED | exact live provider semantics remain unresolved |
| production quota / billing | EXTERNAL BLOCKED | provider account activation and quota state are unverified |

No backend protocol, route, migration, or credential was changed in this phase.

## Production configuration seams

The Android Gradle build and iOS release xcconfig accept only injected provider
client configuration. The native adapters expose normalized provider-neutral
unavailability and never expose provider raw errors or credentials. The static
gate is:

```text
mobile/tool/verify_auth_02e_production_config.py
```

Use `--require-production` only in a release environment that has supplied the
external prerequisites. CI intentionally exercises the missing-input path and
expects a non-zero result.

The iOS Release build phase is a separate build-consumed gate. Required `NO`
keeps unsigned/test builds usable while the runtime remains unavailable;
required `YES` never falls back to a placeholder or test scheme. The production
configuration scripts report `CODE READY / EXTERNAL BLOCKED`, not READY, until
PNVS console binding, Apple registration, billing/quota, credential delivery,
SDK integration, and physical-device acceptance are externally verified.

## Physical-device acceptance matrix

Each row remains `PENDING / EXTERNAL BLOCKED` until a real device and activated
PNVS configuration are available.

| Platform | Carrier | Network / SIM scenarios |
|---|---|---|
| Android | 中国移动 | mobile data; Wi-Fi + SIM; no SIM; data disabled; dual SIM |
| Android | 中国联通 | mobile data; Wi-Fi + SIM; no SIM; data disabled; dual SIM |
| Android | 中国电信 | mobile data; Wi-Fi + SIM; no SIM; data disabled; dual SIM |
| iOS | 中国移动 | mobile data; Wi-Fi + SIM; no SIM; data disabled; dual SIM where supported |
| iOS | 中国联通 | mobile data; Wi-Fi + SIM; no SIM; data disabled; dual SIM where supported |
| iOS | 中国电信 | mobile data; Wi-Fi + SIM; no SIM; data disabled; dual SIM where supported |

For each execution record device model, OS, carrier, SIM/network state, app SHA,
backend SHA, native SDK version, non-secret scheme identifier, and normalized
result. Also run provider unavailable, user cancel, timeout, response loss,
repeated login, privacy revoke, and background/foreground cases.

## Classification

- `READY`: repository identity, fail-closed seams, static gates, and test hooks.
- `CODE READY / EXTERNAL BLOCKED`: implementation can proceed without real PNVS
  values, but production activation cannot.
- `NOT READY`: real provider SDK, scheme binding, credentials, billing, and
  physical-device acceptance.

No production acceptance PASS is claimed in this phase.
