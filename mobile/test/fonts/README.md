# Golden test CJK font

<!-- [人工注释][CI-005] 此字体仅服务于可重复的 Flutter Golden；来源、版本、派生名称和哈希全部固定，禁止回退为 Runner 系统字体。 -->

- Source: Noto CJK Sans 2.004
- Pinned upstream commit: `523d033d6cb47f4a80c58a35753646f5c3608a78`
- Upstream file: `Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf`
- Derived family: `JiYi Golden CJK`
- Derived face: Regular (variable `wght` instantiated at 400)
- Subset corpus: current `mobile/lib/stage1_app.dart`, Golden test text, and printable ASCII
- SHA-256: `8584fed8a70d80c8da17cb62bc549131b1f4bb088f1b24a539d3d8331205b36f`
- License: SIL Open Font License 1.1; see `OFL.txt`

The derived font is intentionally test-only and is loaded with Flutter `FontLoader`; it is not bundled into the production app.
