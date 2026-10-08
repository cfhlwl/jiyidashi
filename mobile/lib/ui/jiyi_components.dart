import 'package:flutter/material.dart';

import 'jiyi_tokens.dart';

// PageFrame 只统一页面容器与标题层级；不持有导航、API 或任何业务状态。
class JiYiPageFrame extends StatelessWidget {
  const JiYiPageFrame({
    super.key,
    required this.title,
    required this.child,
    this.subtitle,
    this.hero,
  });

  final String title;
  final String? subtitle;
  final Widget? hero;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.fromLTRB(
        JiYiSpacing.lg,
        JiYiSpacing.xl,
        JiYiSpacing.lg,
        JiYiSpacing.xxl,
      ),
      children: [
        if (hero != null)
          hero!
        else ...[
          Text(
            title,
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
          if (subtitle != null) ...[
            const SizedBox(height: JiYiSpacing.xs),
            Text(
              subtitle!,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ],
        const SizedBox(height: JiYiSpacing.xl),
        child,
      ],
    );
  }
}

// SectionCard 统一 surface/outline/radius；标题和正文均由调用方提供真实内容，不在组件内补假数据。
class JiYiSectionCard extends StatelessWidget {
  const JiYiSectionCard({
    super.key,
    required this.child,
    this.title,
    this.subtitle,
    this.leading,
    this.padding = const EdgeInsets.all(JiYiSpacing.md),
  });

  final String? title;
  final String? subtitle;
  final Widget? leading;
  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      child: Padding(
        padding: padding,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (title != null || leading != null) ...[
              Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  if (leading != null) ...[
                    leading!,
                    const SizedBox(width: JiYiSpacing.sm),
                  ],
                  if (title != null)
                    Expanded(
                      child: Text(
                        title!,
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                ],
              ),
              if (subtitle != null) ...[
                const SizedBox(height: JiYiSpacing.xs),
                Text(
                  subtitle!,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
              const SizedBox(height: JiYiSpacing.md),
            ] else if (subtitle != null) ...[
              Text(
                subtitle!,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: JiYiSpacing.md),
            ],
            child,
          ],
        ),
      ),
    );
  }
}

enum JiYiStatusKind { info, success, warning, error }

// StatusBanner 统一 success/error/offline/info 的视觉容器；
// message 必须来自真实业务状态，组件本身不推断成功、失败或同步结果。
class JiYiStatusBanner extends StatelessWidget {
  const JiYiStatusBanner({
    super.key,
    required this.kind,
    required this.message,
    this.title,
  });

  final JiYiStatusKind kind;
  final String? title;
  final String message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final semantic = context.jiyiSemanticColors;
    final Color background;
    final Color foreground;
    final IconData icon;

    switch (kind) {
      case JiYiStatusKind.info:
        background = semantic.infoContainer;
        foreground = semantic.onInfoContainer;
        icon = Icons.info_outline;
      case JiYiStatusKind.success:
        background = semantic.successContainer;
        foreground = semantic.onSuccessContainer;
        icon = Icons.check_circle_outline;
      case JiYiStatusKind.warning:
        background = semantic.warningContainer;
        foreground = semantic.onWarningContainer;
        icon = Icons.warning_amber_rounded;
      case JiYiStatusKind.error:
        background = theme.colorScheme.errorContainer;
        foreground = theme.colorScheme.onErrorContainer;
        icon = Icons.error_outline;
    }

    return DecoratedBox(
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(JiYiRadius.control),
      ),
      child: Padding(
        padding: const EdgeInsets.all(JiYiSpacing.md),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: foreground),
            const SizedBox(width: JiYiSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (title != null) ...[
                    Text(
                      title!,
                      style: theme.textTheme.titleSmall?.copyWith(
                        color: foreground,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: JiYiSpacing.xxs),
                  ],
                  Text(
                    message,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      color: foreground,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// EmptyState 用于“没有数据/功能尚未开放”等真实空态；action 由页面显式传入，组件不自动跳转。
class JiYiEmptyState extends StatelessWidget {
  const JiYiEmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.message,
    this.action,
  });

  final IconData icon;
  final String title;
  final String message;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: JiYiSpacing.xl),
      child: Column(
        children: [
          Icon(icon, size: 40, color: theme.colorScheme.onSurfaceVariant),
          const SizedBox(height: JiYiSpacing.sm),
          Text(
            title,
            textAlign: TextAlign.center,
            style: theme.textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: JiYiSpacing.xs),
          Text(
            message,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          if (action != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            action!,
          ],
        ],
      ),
    );
  }
}

class JiYiLoadingState extends StatelessWidget {
  const JiYiLoadingState({super.key, this.message = '正在加载…'});

  final String message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Semantics(
      liveRegion: true,
      label: message,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: JiYiSpacing.xl),
        child: Column(
          children: [
            const SizedBox.square(
              dimension: 28,
              child: CircularProgressIndicator(strokeWidth: 2.5),
            ),
            const SizedBox(height: JiYiSpacing.sm),
            Text(
              message,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class JiYiErrorState extends StatelessWidget {
  const JiYiErrorState({
    super.key,
    required this.title,
    required this.message,
    required this.onRetry,
  });

  final String title;
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return JiYiEmptyState(
      icon: Icons.error_outline,
      title: title,
      message: message,
      action: OutlinedButton.icon(
        onPressed: onRetry,
        icon: const Icon(Icons.refresh),
        label: const Text('重试'),
      ),
    );
  }
}

class JiYiOfflineState extends StatelessWidget {
  const JiYiOfflineState({
    super.key,
    required this.onRetry,
    this.message = '暂时无法连接网络。联网后可以重试。',
  });

  final VoidCallback onRetry;
  final String message;

  @override
  Widget build(BuildContext context) {
    return JiYiEmptyState(
      icon: Icons.cloud_off_outlined,
      title: '当前离线',
      message: message,
      action: OutlinedButton.icon(
        onPressed: onRetry,
        icon: const Icon(Icons.refresh),
        label: const Text('重新连接'),
      ),
    );
  }
}

// ReferenceCard 只负责参考记录排版，不修改 source/type/time 的来源或判断规则。
class JiYiEvidenceCard extends StatelessWidget {
  const JiYiEvidenceCard({
    super.key,
    required this.excerpt,
    required this.source,
    required this.evidenceType,
    required this.occurredAt,
    required this.confidence,
  });

  final String excerpt;
  final String source;
  final String evidenceType;
  final String occurredAt;
  final String confidence;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return JiYiSectionCard(
      leading: Icon(
        Icons.fact_check_outlined,
        color: theme.colorScheme.primary,
      ),
      title: '参考记录',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(excerpt, style: theme.textTheme.bodyLarge),
          const SizedBox(height: JiYiSpacing.sm),
          Wrap(
            spacing: JiYiSpacing.xs,
            runSpacing: JiYiSpacing.xs,
            children: [
              _EvidenceMeta(label: '来源', value: source),
              _EvidenceMeta(label: '类型', value: evidenceType),
              _EvidenceMeta(label: '时间', value: occurredAt),
            ],
          ),
        ],
      ),
    );
  }
}

// Evidence metadata chip 保留 label+value 双文本，避免只靠颜色或图标表达关键可信信息。
class _EvidenceMeta extends StatelessWidget {
  const _EvidenceMeta({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(JiYiRadius.control),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: JiYiSpacing.sm,
          vertical: JiYiSpacing.xs,
        ),
        child: Text('$label：$value', style: theme.textTheme.bodySmall),
      ),
    );
  }
}


/// Production Hero asset boundary. A bundled asset can be supplied later
/// without changing the Today shell; a failed asset load falls back locally.
class TodayHeroBackground extends StatelessWidget {
  const TodayHeroBackground({
    super.key,
    this.assetName,
    required this.fallback,
    this.alignment = Alignment.center,
    this.fit = BoxFit.cover,
  });

  static const defaultAsset = 'assets/brand/today_hero_default.png';

  final String? assetName;
  final Widget fallback;
  final Alignment alignment;
  final BoxFit fit;

  @override
  Widget build(BuildContext context) {
    final asset = assetName?.trim();
    if (asset == null || asset.isEmpty) return fallback;
    return Image.asset(
      asset,
      fit: fit,
      alignment: alignment,
      errorBuilder: (context, error, stackTrace) => fallback,
    );
  }
}

class _TodayHeroFallback extends StatelessWidget {
  const _TodayHeroFallback({required this.atmospheric});

  final bool atmospheric;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Stack(
      fit: StackFit.expand,
      children: [
        DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: theme.brightness == Brightness.dark
                  ? const [Color(0xFF1B304A), Color(0xFF15243A)]
                  : const [Color(0xFFEFF6FB), Color(0xFFFFF4E4)],
            ),
          ),
        ),
        if (atmospheric && theme.brightness == Brightness.light)
          const IgnorePointer(
            child: CustomPaint(painter: _JiYiHeroLandscapePainter()),
          ),
      ],
    );
  }
}

class JiYiHeroHeader extends StatelessWidget {
  const JiYiHeroHeader({
    super.key,
    required this.title,
    this.eyebrow,
    this.subtitle,
    this.icon,
    this.atmospheric = false,
    this.fullBleed = false,
    this.height,
    this.heroAsset,
    this.heroAlignment = Alignment.center,
    this.heroFit = BoxFit.cover,
  });

  final String title;
  final String? eyebrow;
  final String? subtitle;
  final IconData? icon;
  final bool atmospheric;
  final bool fullBleed;
  final double? height;
  final String? heroAsset;
  final Alignment heroAlignment;
  final BoxFit heroFit;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (fullBleed) {
      return SizedBox(
        height: height ?? JiYiTodayGeometry.heroHeight,
        width: double.infinity,
        child: Stack(
          fit: StackFit.expand,
          children: [
            Positioned.fill(
              child: TodayHeroBackground(
                assetName: heroAsset,
                alignment: heroAlignment,
                fit: heroFit,
                fallback: _TodayHeroFallback(atmospheric: atmospheric),
              ),
            ),
            Positioned.fill(
              child: IgnorePointer(
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      stops: const [0.50, 0.86, 1],
                      colors: [
                        Colors.transparent,
                        theme.brightness == Brightness.dark
                            ? const Color(0x33101F32)
                            : const Color(0x18FFFDF8),
                        theme.brightness == Brightness.dark
                            ? const Color(0xFF0D1828)
                            : JiYiTodayVisuals.background,
                      ],
                    ),
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 36, 20, 0),
              child: _buildHeroContent(context),
            ),
          ],
        ),
      );
    }
    return ClipRRect(
      borderRadius: BorderRadius.circular(JiYiRadius.large),
      child: Stack(
        children: [
          Positioned.fill(
            child: TodayHeroBackground(
              assetName: heroAsset,
              alignment: heroAlignment,
              fit: heroFit,
              fallback: _TodayHeroFallback(atmospheric: atmospheric),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(
              JiYiSpacing.xl,
              JiYiSpacing.xl,
              JiYiSpacing.xl,
              JiYiSpacing.xxl,
            ),
            child: _buildHeroContent(context),
          ),
        ],
      ),
    );
  }

  Widget _buildHeroContent(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (eyebrow != null) ...[
                Text(
                  eyebrow!,
                  style: theme.textTheme.labelLarge?.copyWith(
                    color: theme.colorScheme.primary,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.8,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.sm),
              ],
              Text(
                title,
                style: fullBleed
                    ? const TextStyle(
                        color: JiYiTodayVisuals.navy,
                        fontSize: 42,
                        fontWeight: FontWeight.w800,
                        height: 1.0,
                        letterSpacing: -1.2,
                      )
                    : theme.textTheme.headlineMedium?.copyWith(
                        color: theme.colorScheme.onSurface,
                        fontWeight: FontWeight.w800,
                        letterSpacing: -0.6,
                      ),
              ),
              if (subtitle != null) ...[
                const SizedBox(height: 8),
                if (fullBleed)
                  _TodayHeroSubtitle(subtitle: subtitle!)
                else
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 280),
                    child: Text(
                      subtitle!,
                      style: theme.textTheme.bodyLarge?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                        height: 1.55,
                      ),
                    ),
                  ),
              ],
            ],
          ),
        ),
        if (icon != null) ...[
          const SizedBox(width: JiYiSpacing.md),
          DecoratedBox(
            decoration: BoxDecoration(
              color: theme.colorScheme.surface.withValues(alpha: 0.68),
              shape: BoxShape.circle,
            ),
            child: Padding(
              padding: const EdgeInsets.all(JiYiSpacing.sm),
              child: Icon(
                icon,
                size: JiYiIconSize.hero,
                color: theme.colorScheme.primary,
              ),
            ),
          ),
        ],
      ],
    );
  }
}

class _TodayHeroSubtitle extends StatelessWidget {
  const _TodayHeroSubtitle({required this.subtitle});

  final String subtitle;

  @override
  Widget build(BuildContext context) {
    final lines = subtitle.split('\n');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          lines.first,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            color: JiYiTodayVisuals.navy,
            fontSize: 20,
            fontWeight: FontWeight.w500,
            height: 1.1,
            fontFamilyFallback: ['Microsoft YaHei', 'PingFang SC'],
          ),
        ),
        if (lines.length > 1) ...[
          const SizedBox(height: 4),
          Text(
            lines.skip(1).join('\n'),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: JiYiTodayVisuals.secondaryText,
              fontSize: 20,
              fontWeight: FontWeight.w400,
              height: 1.1,
              fontFamilyFallback: ['Microsoft YaHei', 'PingFang SC'],
            ),
          ),
        ],
      ],
    );
  }
}

/// Decorative brand atmosphere only. These mountain/sun shapes never encode
/// location, weather, route, or any other user fact.
class _JiYiHeroLandscapePainter extends CustomPainter {
  const _JiYiHeroLandscapePainter();

  @override
  void paint(Canvas canvas, Size size) {
    final sun = Paint()
      ..color = const Color(0xFFFFDDA8).withValues(alpha: 0.72);
    canvas.drawCircle(
      Offset(size.width * 0.76, size.height * 0.34),
      size.shortestSide * 0.08,
      sun,
    );

    final far = Paint()
      ..color = const Color(0xFFB7CFE0).withValues(alpha: 0.54);
    final farPath = Path()
      ..moveTo(0, size.height * 0.68)
      ..lineTo(size.width * 0.18, size.height * 0.46)
      ..lineTo(size.width * 0.34, size.height * 0.61)
      ..lineTo(size.width * 0.51, size.height * 0.41)
      ..lineTo(size.width * 0.68, size.height * 0.59)
      ..lineTo(size.width * 0.84, size.height * 0.45)
      ..lineTo(size.width, size.height * 0.62)
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();
    canvas.drawPath(farPath, far);

    final haze = Paint()
      ..color = const Color(0xFFEFF5F2).withValues(alpha: 0.74);
    final hazePath = Path()
      ..moveTo(0, size.height * 0.70)
      ..quadraticBezierTo(
        size.width * 0.26,
        size.height * 0.56,
        size.width * 0.52,
        size.height * 0.69,
      )
      ..quadraticBezierTo(
        size.width * 0.78,
        size.height * 0.81,
        size.width,
        size.height * 0.63,
      )
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();
    canvas.drawPath(hazePath, haze);

    final near = Paint()
      ..color = const Color(0xFF789DB2).withValues(alpha: 0.34);
    final nearPath = Path()
      ..moveTo(0, size.height * 0.8)
      ..lineTo(size.width * 0.22, size.height * 0.63)
      ..lineTo(size.width * 0.43, size.height * 0.78)
      ..lineTo(size.width * 0.62, size.height * 0.58)
      ..lineTo(size.width * 0.82, size.height * 0.72)
      ..lineTo(size.width, size.height * 0.61)
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();
    canvas.drawPath(nearPath, near);

    final lake = Paint()
      ..color = const Color(0xFFB7D9E7).withValues(alpha: 0.36);
    final lakePath = Path()
      ..moveTo(0, size.height * 0.79)
      ..quadraticBezierTo(
        size.width * 0.28,
        size.height * 0.73,
        size.width * 0.56,
        size.height * 0.80,
      )
      ..quadraticBezierTo(
        size.width * 0.78,
        size.height * 0.86,
        size.width,
        size.height * 0.76,
      )
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();
    canvas.drawPath(lakePath, lake);
  }

  @override
  bool shouldRepaint(_JiYiHeroLandscapePainter oldDelegate) => false;
}

class JiYiSectionHeader extends StatelessWidget {
  const JiYiSectionHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.trailing,
  });

  final String title;
  final String? subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: theme.textTheme.titleLarge?.copyWith(
                  fontWeight: FontWeight.w800,
                ),
              ),
              if (subtitle != null) ...[
                const SizedBox(height: JiYiSpacing.xxs),
                Text(
                  subtitle!,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ],
          ),
        ),
        if (trailing != null) trailing!,
      ],
    );
  }
}

class JiYiActionCard extends StatelessWidget {
  const JiYiActionCard({
    super.key,
    required this.icon,
    required this.title,
    required this.message,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String message;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.surface,
      borderRadius: BorderRadius.circular(JiYiRadius.card),
      child: InkWell(
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(JiYiSpacing.lg),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              DecoratedBox(
                decoration: BoxDecoration(
                  color: theme.colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(JiYiRadius.control),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(JiYiSpacing.sm),
                  child: Icon(
                    icon,
                    color: theme.colorScheme.primary,
                    size: JiYiIconSize.medium,
                  ),
                ),
              ),
              const SizedBox(width: JiYiSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: JiYiSpacing.xs),
                    Text(
                      message,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                        height: 1.5,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: JiYiSpacing.sm),
              const Icon(Icons.chevron_right),
            ],
          ),
        ),
      ),
    );
  }
}
