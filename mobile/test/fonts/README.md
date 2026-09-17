# Golden test CJK font

<!-- [人工注释][CI-005] 此字体仅服务于可重复的 Flutter Golden；来源、版本、派生名称和哈希全部固定，禁止回退为 Runner 系统字体。 -->

<!-- [人工注释][S1-027] Stage 1G 扩充确定性 CJK 子集到当前 Flutter 可见源码字符，并用 cmap coverage gate 防止 Golden 再次冻结缺字空白。 -->
- Source: Noto CJK Sans 2.004
- Pinned upstream commit: `523d033d6cb47f4a80c58a35753646f5c3608a78`
- Upstream file: `Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf`
- Derived family: `JiYi Golden CJK`
- Derived face: Regular (variable `wght` instantiated at 400)
- Subset corpus: current `mobile/lib/**/*.dart`, `mobile/test/visual_golden_test.dart`, and printable ASCII
- Subset tool: `fonttools 4.59.2`
- SHA-256: `c07a6646153eabe2f78d08131a71f8dff8d29d4fa6313d6e593681be38f18955`
- License: SIL Open Font License 1.1; see `OFL.txt`

The derived font is intentionally test-only and is loaded with Flutter `FontLoader`; it is not bundled into the production app.

## Material Icons test font

<!-- [人工注释][CI-005] 图标 Golden 使用 Flutter 3.47.4 自身固定的 MaterialIcons 字体，来源和哈希均冻结，禁止回退到 Runner 系统字体。 -->

- Source: Flutter 3.47.4 SDK `material_fonts` cache
- Flutter `material_fonts.version`: `flutter_infra_release/flutter/fonts/3012db47f3130e62f7cc0beabff968a33cbec8d8/fonts.zip`
- Extracted file: `bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf`
- Test font family: `MaterialIcons`
- SHA-256: `d9865b671a09d683d13a863089d8825e0f61a37696ce5d7d448bc8023aa62453`
- License: Apache License 2.0; see `MATERIAL_ICONS_LICENSE.txt`

This font is committed only for deterministic Flutter Golden tests and is not added to the production app bundle.
