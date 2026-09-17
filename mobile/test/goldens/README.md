# Flutter Golden 基线

<!-- [人工注释][CI-005] 这些 PNG 是 CI-005 的可审查视觉资产；普通 CI 不得自动更新。 -->

首阶段权威环境固定为 Flutter 3.47.4 / Ubuntu、390×844、DPR 1.0、`zh-CN`、UTC。

显式更新命令：

```bash
cd mobile
flutter test --update-goldens test/visual_golden_test.dart
```

更新 PNG 后必须人工审查 diff，再与测试代码一起提交。CI 失败时 `visual-preview` 会上传当前基线和 `test/failures/**` 差异产物。
