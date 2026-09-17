import 'package:flutter/material.dart';

import 'jiyi_tokens.dart';

// [人工注释][S1-027] 生产 Theme 与 Golden 共用这一单一事实源；G1 保持现有 seed/background 不变，
// 只集中配置入口并挂载语义色 extension，因此本提交预期 Golden 像素 0 漂移。
abstract final class JiYiTheme {
  static const Color brandSeed = Color(0xFF446A57);
  static const Color appBackground = Color(0xFFF7F8F6);

  static ThemeData light({String? fontFamily}) {
    return ThemeData(
      useMaterial3: true,
      colorSchemeSeed: brandSeed,
      scaffoldBackgroundColor: appBackground,
      fontFamily: fontFamily,
      extensions: const <ThemeExtension<dynamic>>[
        JiYiSemanticColors.light,
      ],
    );
  }
}
