# AMap Flutter bridge supply-chain deviation review

Status: **APPROVED FOR PR #205 ONLY, pending second-round reviewer acceptance**

## Decision

JiYi keeps `csp_amap_flutter_map 1.1.1` as a narrowly approved compatibility
bridge instead of silently pretending it is the official AMap Flutter package.

This is an explicit deviation from Issue #204's preferred
`amap_flutter_map 3.0.0` path. The deviation exists because the official
3.0.0 package is not compatible with the repository's current Dart/Flutter and
Android Gradle toolchain without maintaining a substantial local fork.

The bridge is **not** treated as an authority source for place, visit, route, or
location data. It is presentation-only. Canonical coordinates continue to come
from JiYi's backend Place/Visit projections.

## Reviewed artifact

- Package: `csp_amap_flutter_map`
- Version: **1.1.1** (exact, no caret/range)
- Source registry: **pub.dev**
- Locked archive SHA-256:
  `54dff0f39a5e48f0f668512bdba38a36dbcb63386db94491c6054f45cf435758`
- Publisher status on pub.dev: **unverified uploader**
- Repository advertised by package: `https://gitee.com/chenshipeng0914/csp_amap_flutter_map.git`
- Direct Dart dependencies advertised by pub.dev: Flutter,
  `flutter_plugin_android_lifecycle`, `meta`,
  `plugin_platform_interface`
- Base types are bundled into the package as of the 1.1.x line.

The unverified publisher is a real supply-chain risk. Approval is therefore
conditional on the pinning controls below; this review does not generalize to a
future version.

## Why the preferred official package is not used directly

The AMap documentation still points Flutter applications at
`amap_flutter_map 3.0.0`. That release is several years old and declares a
pre-Dart-3 SDK range. Public AMap issue reports also document modern Gradle
namespace incompatibility in the 3.0.0 Android plugin.

JiYi will not download an arbitrary community fork at build time to work around
those incompatibilities. Doing so would move the same supply-chain problem to a
Git dependency.

## Compensating controls

1. `mobile/pubspec.yaml` must use exactly `csp_amap_flutter_map: 1.1.1`.
2. `mobile/pubspec.lock` must retain the exact pub.dev SHA-256 above.
3. CI runs `tool/check_amap_bridge_pin.py`; package name, version, registry,
   checksum, or dependency syntax drift fails the build.
4. No Git branch, Gitee `develop`, path override, or version range is allowed.
5. AMap Android/iOS keys remain build-time values; no real key is committed.
6. Privacy consent is obtained and visibly disclosed before AMap SDK
   initialization.
7. Production without the platform AMap key fails closed at startup.
8. The bridge never substitutes device current location for canonical Visit
   coordinates and never promotes a drawn connector to a real GPS route.
9. Any future bridge upgrade requires a new supply-chain review and an updated
   checksum in this document and CI gate.

## Re-review trigger

Any change to the package name, version, pub.dev archive checksum, source
registry, native AMap dependency behavior, permissions, privacy API, or
platform implementation reopens this approval.
