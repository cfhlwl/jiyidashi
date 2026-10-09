# BRAND_ICON_009 — A2 Optical Centering

## Locked input and selected correction

- Original design authority: `mobile/design_reference/brand/icon-008/jiyi-neural-imprint-a2.svg`
- Original A2 SVG SHA256: `BDE520B6C71C2AC16E97F727EB8ECB192F6F3994E8354CEDEB404C175F610372`
- Background is excluded from all measurements.
- Selected correction: **C2**, `translate(-68 -22)` applied to the two organic forms and the warm-gold core together as a single group.
- No element was independently moved, scaled, recoloured, reshaped, or redrawn.

## Measurement

| Variant | Subject bounds | Luminance-weighted visual centroid |
| --- | --- | --- |
| Original | `(274, 246)–(898, 865)` | `(589.3, 568.4)` |
| C1, left 56 / up 16 | `(218, 230)–(842, 849)` | `(533.3, 552.4)` |
| C2, left 68 / up 22 | `(206, 224)–(830, 843)` | `(521.3, 546.4)` |

C2 is selected because it produces the most natural 60pt iOS home-screen balance without making the symbol feel overcorrected to the upper-left.

## Outputs

- `ios-home-optical-centering-review.png`: Original, C1 and C2 at actual 60pt / 180px iOS home-screen icon size.
- `a2-optical-centering-review-board.png`: large-format review board with the three candidates.
- `jiyi-neural-imprint-a2-centered-c2.svg`: final vector source for this integration; it retains the original A2 paths and colours inside one translation group.
- `jiyi-neural-imprint-a2-centered-final-1024.png`: raster evidence export of the selected C2 master.

## Platform integration

- iOS: every entry in the existing `AppIcon.appiconset/Contents.json` has been regenerated from C2. Files are opaque RGB PNGs with the navy field on every edge; no white border, baked corner radius, or additional shadow.
- Android: all legacy mipmap densities, API 26+ Adaptive foreground/background and API 33+ monochrome layers were regenerated from C2.
- The Android Adaptive layer keeps the same platform-only uniform 72% safety inset already used by BRAND-ICON-008. C2 content remains inside the conservative 66dp safe circle.
- App display name remains `迹忆`; Bundle ID and Android application ID remain `com.jiyidays`.

## Validation status

| Check | Status |
| --- | --- |
| iOS AppIcon catalog slots and dimensions | PASS |
| Android legacy density resources | PASS |
| Android Adaptive and monochrome resources | PASS |
| Android Adaptive conservative safe circle | PASS |
| UI / App ID / signing / business code changes | NONE |
| iOS build | BLOCKED — Windows host has no macOS/Xcode toolchain |
| Android Debug/Release build | BLOCKED — Flutter SDK and `mobile/local.properties` are unavailable; signing was not changed |

Status: `READY_FOR_REVIEW`.
