import 'package:flutter/material.dart';

// G 线 spacing 只保留少量可复用档位，逐步替代页面散落 magic numbers；数值本身不承载业务语义。
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

// Today V3 structure anchors. These values describe the primary 390x844 review
// viewport; they are geometry anchors, not business or typography tokens.
abstract final class JiYiTodayGeometry {
  static const double pageHorizontalPadding = 13;
  static const double heroHeight = 167;
  static const double heroFootprintOverlap = 16;
  static const double footprintCardHeight = 239;
  static const double mapViewportHeight = 156;
  static const double sectionGap = 12;
  static const double memorySectionHeight = 259;
  static const double quickCaptureHeight = 94;
  static const double bottomNavigationContentHeight = 48;
}

// Radius token 只统一视觉曲率，不替代 Material 控件本身的交互/可访问性行为。
abstract final class JiYiRadius {
  static const double control = 12;
  static const double card = 16;
  static const double large = 24;
  static const double sheet = 28;
  static const double pill = 999;
}

// Product Experience V2 visual tokens. These complement Material ColorScheme without
// changing existing authority/state behavior.
abstract final class JiYiProductColors {
  static const Color brandPrimary = Color(0xFF356A9A);
  static const Color brandSecondary = Color(0xFF6F7F91);
  static const Color background = Color(0xFFF7F4EE);
  static const Color surface = Color(0xFFFFFDF9);
  static const Color surfaceElevated = Color(0xFFFFFFFF);
  static const Color surfaceSoft = Color(0xFFEEF3F7);
  static const Color textPrimary = Color(0xFF1D2732);
  static const Color textSecondary = Color(0xFF5E6975);
  static const Color textTertiary = Color(0xFF7A8590);
  static const Color border = Color(0xFFDCE3E8);
  static const Color divider = Color(0xFFE8EDF0);
  static const Color aiAssisted = Color(0xFF7467A7);
  static const Color family = Color(0xFF7A6395);
  static const Color location = Color(0xFFBD7544);
  static const Color media = Color(0xFF4F7D69);
}

abstract final class JiYiIconSize {
  static const double small = 18;
  static const double medium = 24;
  static const double large = 32;
  static const double hero = 40;
}

abstract final class JiYiTapTarget {
  static const double normal = 48;
  static const double elder = 56;
}

abstract final class JiYiMotion {
  static const Duration fast = Duration(milliseconds: 140);
  static const Duration standard = Duration(milliseconds: 220);
  static const Duration emphasized = Duration(milliseconds: 320);
  static const Curve easing = Curves.easeOutCubic;
}

// Material ColorScheme 没有 success/warning/info 三类产品状态色；
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

  static const dark = JiYiSemanticColors(
    success: Color(0xFF7CE0AB),
    onSuccess: Color(0xFF082114),
    successContainer: Color(0xFF143E29),
    onSuccessContainer: Color(0xFFC6F8D9),
    warning: Color(0xFFFFD080),
    onWarning: Color(0xFF2D1B00),
    warningContainer: Color(0xFF4A330F),
    onWarningContainer: Color(0xFFFFE7B9),
    info: Color(0xFF9CC7FF),
    onInfo: Color(0xFF071D3B),
    infoContainer: Color(0xFF17385E),
    onInfoContainer: Color(0xFFD6E8FF),
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
  JiYiSemanticColors lerp(covariant JiYiSemanticColors? other, double t) {
    if (other == null) return this;
    return JiYiSemanticColors(
      success: Color.lerp(success, other.success, t)!,
      onSuccess: Color.lerp(onSuccess, other.onSuccess, t)!,
      successContainer: Color.lerp(
        successContainer,
        other.successContainer,
        t,
      )!,
      onSuccessContainer: Color.lerp(
        onSuccessContainer,
        other.onSuccessContainer,
        t,
      )!,
      warning: Color.lerp(warning, other.warning, t)!,
      onWarning: Color.lerp(onWarning, other.onWarning, t)!,
      warningContainer: Color.lerp(
        warningContainer,
        other.warningContainer,
        t,
      )!,
      onWarningContainer: Color.lerp(
        onWarningContainer,
        other.onWarningContainer,
        t,
      )!,
      info: Color.lerp(info, other.info, t)!,
      onInfo: Color.lerp(onInfo, other.onInfo, t)!,
      infoContainer: Color.lerp(infoContainer, other.infoContainer, t)!,
      onInfoContainer: Color.lerp(onInfoContainer, other.onInfoContainer, t)!,
    );
  }
}

// 组件通过 context 读取统一语义色；缺失 extension 时 fail-safe 回退到 light token，避免测试/嵌入场景崩溃。
extension JiYiSemanticColorsContext on BuildContext {
  JiYiSemanticColors get jiyiSemanticColors =>
      Theme.of(this).extension<JiYiSemanticColors>() ??
      JiYiSemanticColors.light;
}
