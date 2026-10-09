# BRAND_ICON_008

## Locked master

- Selected Master: `A2 — 更平面`
- Authoritative source: `jiyi-neural-imprint-a2.svg`
- Source SVG SHA256: `21600FA80D3B841CF7F12D80172B60ECD0237880B104766AE2F7D6BDEAA93E23`
- Design changed: `NO`

The SVG is copied byte-for-byte from BRAND-ICON-007 into this delivery folder for audit. All platform images are derived from this locked A2 master; A1 and A3 are not used.

## Integrated resources

### iOS

- Updated `Runner/Assets.xcassets/AppIcon.appiconset` for every image declared by the existing `Contents.json`, including the 1024px marketing asset.
- Every generated file is an opaque square RGB PNG with the approved navy field reaching all four edges. No baked corner radius or additional shadow is included.
- `CFBundleDisplayName` is now `迹忆`.

### Android

- Updated all legacy `mipmap-*/ic_launcher.png` densities.
- Added Android Adaptive Icon resources for API 26+ and a themed monochrome layer for API 33+.
- Adaptive foreground is a uniform 72% scale of the unchanged A2 construction. This platform-only inset keeps the entire mark, including the warm-gold core, within Android's conservative 66dp safe circle under circular and rounded-square masks; no relative shape, colour, or position has changed.
- `android:label` is now `迹忆`; `android:roundIcon` resolves to the same launcher asset.

## Identity check

| Item | Value | Result |
| --- | --- | --- |
| App Display Name | `迹忆` | PASS |
| iOS Bundle ID | `com.jiyidays` | PASS |
| Android applicationId | `com.jiyidays` | PASS |
| Dart package | `jiyidashi` | PASS |
| Signature / business integrations | unchanged | PASS |

## Asset checks

| Check | Result |
| --- | --- |
| iOS AppIcon catalog dimensions and opaque RGB PNGs | PASS |
| Android legacy density dimensions | PASS |
| Android Adaptive foreground/background resources | PASS |
| Android monochrome themed resource | PASS |
| Conservative Adaptive safe circle | PASS (`127.6px <= 132px` at xxxhdpi 432px canvas) |
| 32px / 60px / 180px A2 review previews | PASS |

## Build status

| Build | Status | Reason |
| --- | --- | --- |
| iOS | BLOCKED | This Windows host does not provide Xcode/macOS tooling. |
| Android Debug | BLOCKED | Flutter SDK is unavailable and `mobile/local.properties` is absent, so Gradle cannot load Flutter's build plugin. |
| Android Release | BLOCKED | Same local Flutter SDK prerequisite; release signing configuration was not changed. |

No production deployment, merge, signing update, App ID change, UI V3 change, or business-code change is included.
