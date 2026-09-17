import 'package:flutter/material.dart';

// [人工注释][S1-027] G 线 spacing 只保留少量可复用档位，逐步替代页面散落 magic numbers；数值本身不承载业务语义。
abstract final class JiYiSpacing {
  static const double xxs = 4;
  static const double xs = 8;
  static const double sm = 12;
  static const double md = 16;
  static const double lg = 20;
  static const double xl = 24;
  static const double xxl = 32;
  static const double xxxl = 40;
  static const double hero = 48;
}

// [人工注释][S1-027] Radius token 只统一视觉曲率，不替代 Material 控件本身的交互/可访问性行为。
abstract final class JiYiRadius {
  static const double control = 12;
  static const double card = 16;
  static const double large = 24;
}

// [人工注释][S1-027] Material ColorScheme 没有 success/warning/info 三类产品状态色；
// 用 ThemeExtension 补足，并始终配套文字/图标，禁止仅靠颜色表达状态。
@immutable
class JiYiSemanticColors extends ThemeExtension<JiYiSemanticColors> {
  const JiYiSemanticColors({
    required this.success,
    required this.onSuccess,
    required this.successContainer,
    required this.onSuccessContainer,
    required this.warning,
    required this.onWarning,
    required this.warningContainer,
    required this.onWarningContainer,
    required this.info,
    required this.onInfo,
    required this.infoContainer,
    required this.onInfoContainer,
  });

  static const light = JiYiSemanticColors(
    success: Color(0xFF24613E),
    onSuccess: Color(0xFFFFFFFF),
    successContainer: Color(0xFFD9F2E3),
    onSuccessContainer: Color(0xFF0D2D1C),
    warning: Color(0xFF7A4D00),
    onWarning: Color(0xFFFFFFFF),
    warningContainer: Color(0xFFFFE2AD),
    onWarningContainer: Color(0xFF2A1800),
    info: Color(0xFF315D7D),
    onInfo: Color(0xFFFFFFFF),
    infoContainer: Color(0xFFD5E9FA),
    onInfoContainer: Color(0xFF0C2A3E),
  );

  final Color success;
  final Color onSuccess;
  final Color successContainer;
  final Color onSuccessContainer;
  final Color warning;
  final Color onWarning;
  final Color warningContainer;
  final Color onWarningContainer;
  final Color info;
  final Color onInfo;
  final Color infoContainer;
  final Color onInfoContainer;

  @override
  JiYiSemanticColors copyWith({
    Color? success,
    Color? onSuccess,
    Color? successContainer,
    Color? onSuccessContainer,
    Color? warning,
    Color? onWarning,
    Color? warningContainer,
    Color? onWarningContainer,
    Color? info,
    Color? onInfo,
    Color? infoContainer,
    Color? onInfoContainer,
  }) {
    return JiYiSemanticColors(
      success: success ?? this.success,
      onSuccess: onSuccess ?? this.onSuccess,
      successContainer: successContainer ?? this.successContainer,
      onSuccessContainer: onSuccessContainer ?? this.onSuccessContainer,
      warning: warning ?? this.warning,
      onWarning: onWarning ?? this.onWarning,
      warningContainer: warningContainer ?? this.warningContainer,
      onWarningContainer: onWarningContainer ?? this.onWarningContainer,
      info: info ?? this.info,
      onInfo: onInfo ?? this.onInfo,
      infoContainer: infoContainer ?? this.infoContainer,
      onInfoContainer: onInfoContainer ?? this.onInfoContainer,
    );
  }

  @override
  JiYiSemanticColors lerp(
    covariant JiYiSemanticColors? other,
    double t,
  ) {
    if (other == null) return this;
    return JiYiSemanticColors(
      success: Color.lerp(success, other.success, t)!,
      onSuccess: Color.lerp(onSuccess, other.onSuccess, t)!,
      successContainer:
          Color.lerp(successContainer, other.successContainer, t)!,
      onSuccessContainer:
          Color.lerp(onSuccessContainer, other.onSuccessContainer, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      onWarning: Color.lerp(onWarning, other.onWarning, t)!,
      warningContainer:
          Color.lerp(warningContainer, other.warningContainer, t)!,
      onWarningContainer:
          Color.lerp(onWarningContainer, other.onWarningContainer, t)!,
      info: Color.lerp(info, other.info, t)!,
      onInfo: Color.lerp(onInfo, other.onInfo, t)!,
      infoContainer: Color.lerp(infoContainer, other.infoContainer, t)!,
      onInfoContainer:
          Color.lerp(onInfoContainer, other.onInfoContainer, t)!,
    );
  }
}

// [人工注释][S1-027] 组件通过 context 读取统一语义色；缺失 extension 时 fail-safe 回退到 light token，避免测试/嵌入场景崩溃。
extension JiYiSemanticColorsContext on BuildContext {
  JiYiSemanticColors get jiyiSemanticColors =>
      Theme.of(this).extension<JiYiSemanticColors>() ??
      JiYiSemanticColors.light;
}
