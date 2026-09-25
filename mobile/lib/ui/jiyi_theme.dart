import 'package:flutter/material.dart';

import 'jiyi_tokens.dart';

// JiYiTheme 是 Flutter 产品视觉的唯一事实源；页面不得再次复制品牌色、输入框、按钮、Card、Dialog 或底部导航样式。
abstract final class JiYiTheme {
  static const Color brandSeed = Color(0xFF446A57);
  static const Color appBackground = Color(0xFFF7F8F6);

  static ThemeData light({String? fontFamily, bool elderMode = false}) {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: brandSeed,
      brightness: Brightness.light,
    );
    final base = ThemeData(
      useMaterial3: true,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: appBackground,
      fontFamily: fontFamily,
      extensions: const <ThemeExtension<dynamic>>[JiYiSemanticColors.light],
    );

    final elderTextTheme = elderMode
        ? base.textTheme.copyWith(
            bodySmall: base.textTheme.bodySmall?.copyWith(fontSize: 16, height: 1.6),
            bodyMedium: base.textTheme.bodyMedium?.copyWith(fontSize: 18, height: 1.65),
            bodyLarge: base.textTheme.bodyLarge?.copyWith(fontSize: 20, height: 1.65),
            titleSmall: base.textTheme.titleSmall?.copyWith(fontSize: 19, height: 1.5),
            titleMedium: base.textTheme.titleMedium?.copyWith(fontSize: 22, height: 1.5),
            headlineSmall: base.textTheme.headlineSmall?.copyWith(fontSize: 30, height: 1.35),
          )
        : base.textTheme;

    // Elder Mode extends the same design system: typography/targets/spacing only.
    return base.copyWith(
      textTheme: elderTextTheme.copyWith(
        displaySmall: base.textTheme.displaySmall?.copyWith(
          fontWeight: FontWeight.w800,
          letterSpacing: -0.6,
        ),
        headlineSmall: base.textTheme.headlineSmall?.copyWith(
          fontWeight: FontWeight.w700,
          letterSpacing: -0.2,
        ),
        titleMedium: base.textTheme.titleMedium?.copyWith(
          fontWeight: FontWeight.w700,
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: colorScheme.surface,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: JiYiSpacing.md,
          vertical: JiYiSpacing.md,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(JiYiRadius.control),
          borderSide: BorderSide(color: colorScheme.outlineVariant),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(JiYiRadius.control),
          borderSide: BorderSide(color: colorScheme.outlineVariant),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(JiYiRadius.control),
          borderSide: BorderSide(color: colorScheme.primary, width: 1.6),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(JiYiRadius.control),
          borderSide: BorderSide(color: colorScheme.error),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: Size(0, elderMode ? 56 : 48),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(JiYiRadius.control),
          ),
          textStyle: base.textTheme.labelLarge?.copyWith(
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: Size(0, elderMode ? 56 : 48),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(JiYiRadius.control),
          ),
          side: BorderSide(color: colorScheme.outlineVariant),
          textStyle: base.textTheme.labelLarge?.copyWith(
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          minimumSize: Size(0, elderMode ? 48 : 44),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(JiYiRadius.control),
          ),
        ),
      ),
      cardTheme: CardThemeData(
        margin: EdgeInsets.zero,
        elevation: 0,
        color: colorScheme.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(JiYiRadius.card),
          side: BorderSide(color: colorScheme.outlineVariant),
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        height: elderMode ? 84 : 72,
        elevation: 0,
        backgroundColor: colorScheme.surface,
        indicatorColor: colorScheme.secondaryContainer,
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return base.textTheme.labelMedium?.copyWith(
            fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
            color: selected
                ? colorScheme.onSecondaryContainer
                : colorScheme.onSurfaceVariant,
          );
        }),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: colorScheme.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(JiYiRadius.large),
        ),
      ),
      chipTheme: base.chipTheme.copyWith(
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(JiYiRadius.control),
          side: BorderSide(color: colorScheme.outlineVariant),
        ),
      ),
      dividerTheme: DividerThemeData(
        color: colorScheme.outlineVariant,
        thickness: 1,
        space: 1,
      ),
    );
  }
}
