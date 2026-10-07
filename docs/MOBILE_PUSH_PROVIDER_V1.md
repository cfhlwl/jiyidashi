# NOTIFY-001B Mobile Push Provider Decision V1

## Status

This document is the reviewed provider decision record for NOTIFY-001B.

Current code shape:

- iOS: APNs token provider API.
- Android with Google Mobile Services: FCM HTTP v1.
- Android with a configured Huawei Mobile Services runtime: HMS Push Kit.
- TEST provider: development/test only; production registration rejects it.
- The historical application identity `cn.jiyidashi.jiyidashi` remains unchanged.
- Live provider enablement remains blocked until APP-ID-001 establishes the final reviewed app identity.

This is **not** a declaration that mainland-China Android production coverage is complete.
Xiaomi / OPPO / vivo-class devices without reliable Google Play Services and without the reviewed
HMS path currently degrade to `providerUnavailable`. Physical/provider acceptance therefore
remains HOLD until a reviewed OEM/aggregation path is added and proven on real devices.

## Android provider matrix

| Device/runtime class | V1 provider | Token authority | Background / terminated delivery | Credential burden | Privacy / routing | V1 fallback |
| --- | --- | --- | --- | --- | --- | --- |
| Google-services-capable Android | FCM | Firebase installation token, uploaded only under authenticated owner + canonical client_uuid | FCM service receives data message; app posts reviewed local notification and persists typed tap | Google project + mobile Firebase identifiers; server service-account credential | Delivery metadata routes through Google/Firebase | If GMS/provider config unavailable, fail closed as provider unavailable |
| Huawei device with HMS available | HMS Push Kit | HMS push token, uploaded with actual provider provenance `HMS` | HMS message service receives data payload; same local notification/tap contract | AppGallery/HMS app registration + server client credential | Delivery metadata routes through Huawei Push Kit | If HMS config/runtime unavailable, evaluate FCM only when GMS is actually available |
| Honor-class device | Runtime capability based; HMS only when HMS is actually present/configured, otherwise FCM when GMS is present/configured | Same as selected provider | Same typed native bridge | Depends on selected runtime/provider | Depends on selected provider | Brand name alone never selects provider |
| Mainland China Android without reliable GMS, but reviewed HMS path available | HMS | HMS token | HMS service | Huawei provider credentials | Huawei routing | HMS |
| Xiaomi / OPPO / vivo-class mainland device without reliable GMS and without reviewed HMS support | **Unsupported for production PASS in V1** | None accepted | No imitation background service | Future OEM or aggregation credential set required | Must be reviewed before adoption | Truthful `providerUnavailable`; no FCM masquerading |
| Emulator / TEST path | TEST only outside production | Synthetic | CI only | None | No production routing | Never accepted as production evidence |

## Why FCM + HMS

The server notification authority is already provider-neutral and records actual provider provenance.
Using separate `FCM` and `HMS` adapters preserves that model and avoids overloading FCM to mean
an unrelated mainland-China channel.

The V1 client selector is capability based:

1. use HMS when HMS is configured and the Huawei services runtime is present;
2. otherwise use FCM when FCM is configured and Google Play Services is present;
3. otherwise report provider unavailable.

No hidden always-on background service is added to imitate push delivery.

## Xiaomi / OPPO / vivo gap

NOTIFY-001B explicitly forbids treating FCM-only evidence as mainland-China production acceptance.
The current code therefore does **not** claim an OEM channel it has not implemented.

Before closing physical/provider acceptance, choose and review one of:

- an aggregation provider with explicit Xiaomi / OPPO / vivo OEM channel support; or
- direct OEM integrations represented by distinct provider provenance values and server adapters.

That follow-up must document provider terms, data routing, credential custody, per-vendor token
lifecycle, invalid-token classification, background restrictions, operational cost, and real-device
evidence. A provider enum/schema extension must remain backward compatible.

## Token and owner lifecycle

The mobile app uses the existing secure installation ID as canonical `client_uuid`; it does not
create a second push identity.

Rules:

- a native token obtained before login is retained locally but is not uploaded for an unknown owner;
- token registration uses the current authenticated session generation;
- token rotation re-registers through the same `PUT /v1/notifications/device` authority;
- same-provider token rebinding is serialized by the NOTIFY-001A disclosure handoff;
- logout revokes the server binding and retires the native provider token;
- auth logout/session revoke also fences the canonical Device binding server-side;
- account switch fences active push bindings belonging to another owner on the same client_uuid
  before the new public session is issued;
- failed provider-token retirement is durable and blocks reuse by the next owner until retirement
  succeeds;
- raw provider tokens are never written to app logs;
- native iOS/Android layers do not persist raw tokens outside the Flutter secure token store.

## Typed payload and navigation

Only this V1 contract crosses the native/Flutter boundary:

```text
version = 1
destination = HOME | REMINDER | MEMORY | APP_UPDATE | FAMILY | EXPORT
resource_id = optional UUID
```

Unknown versions are rejected. Unknown destinations and malformed resource identifiers fail closed
to HOME. Push payloads never execute arbitrary URLs or open WebViews/external URLs.

Current safe routes:

- HOME -> existing Today/home surface;
- FAMILY -> existing Family surface;
- REMINDER -> existing Reminder page;
- MEMORY + UUID -> existing Memory detail API/data authority;
- APP_UPDATE / EXPORT -> HOME until those reviewed product destinations exist.

## App identity gate

Do not provision or accept live APNs/FCM/HMS production bindings against the historical identifier
until APP-ID-001 resolves the final application identity.

Production server configuration remains fail closed behind:

```text
PUSH_APP_IDENTITY_REVIEWED=true
```

APNs additionally requires `APNS_TOPIC == PUSH_IOS_BUNDLE_ID` and the production APNs endpoint.
Android provider registrations require the reviewed Android application identity plus the selected
provider configuration.

## Credential custody and rotation

No server private credential belongs in the repository, mobile binary, notification error row, or
Admin browser payload.

### APNs

Server-only inputs:

```text
APNS_TEAM_ID
APNS_KEY_ID
APNS_PRIVATE_KEY or APNS_PRIVATE_KEY_FILE
APNS_TOPIC
APNS_ENVIRONMENT
```

Rotation procedure:

1. create/approve the replacement APNs signing key under the final reviewed Apple app identity;
2. place the new key in the deployment secret store or secret-mounted file;
3. update key ID/material together and restart API/worker processes so cached provider JWTs are
   discarded;
4. prove a physical-device delivery in the intended sandbox/TestFlight/production environment;
5. revoke the old Apple key only after the new path is confirmed;
6. if compromise is suspected, disable APNs routing first, revoke the key, then provision replacement
   authority.

### FCM

Server-only secret is the service-account private key. Mobile Firebase project/app identifiers are
build-time provider identity inputs, not server private keys.

Rotation procedure:

1. create a replacement service-account credential with only required Firebase messaging authority;
2. update the server secret value/file and restart provider processes;
3. verify OAuth token exchange and real-device FCM delivery;
4. revoke/delete the old service-account key;
5. on compromise, disable FCM routing before rotating.

### HMS

Server-only secret is `HMS_CLIENT_SECRET`; mobile needs only reviewed app identity/configuration.

Rotation procedure:

1. rotate the HMS client credential in the provider console;
2. update the deployment secret and restart provider processes;
3. verify OAuth exchange and physical HMS device delivery;
4. revoke the superseded credential;
5. on compromise, disable HMS routing until replacement authority is installed.

## Acceptance boundary

Code/CI PASS and provider/physical-device PASS are separate.

Code/CI may PASS with live providers disabled. Production/provider acceptance remains HOLD until:

- APP-ID-001 final identity is authoritative;
- real APNs credentials are bound to that identity;
- real Android provider credentials are bound to the reviewed final identity;
- physical iOS evidence passes;
- physical Google-services Android evidence passes;
- a reviewed mainland-China path (including the currently unsupported Xiaomi/OPPO/vivo class)
  passes on a representative physical device.
