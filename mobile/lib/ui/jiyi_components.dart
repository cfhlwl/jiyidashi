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
    this.eyebrow,
    this.trailing,
  });

  final String title;
  final String? subtitle;
  final Widget? hero;
  final String? eyebrow;
  final Widget? trailing;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(JiYiSpacing.lg, 12, JiYiSpacing.lg, 96),
      children: [
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (hero != null)
                hero!
              else
                _JiYiPageTitle(
                  title: title,
                  subtitle: subtitle,
                  eyebrow: eyebrow,
                  trailing: trailing,
                ),
              const SizedBox(height: JiYiSpacing.xl),
              child,
            ],
          ),
        ),
      ],
    );
  }
}

/// A restrained atmospheric surface used by the memory pages. It gives the
/// screen a recognisable opening without inventing a photo or masking a real
/// record. The cool-blue gradients are deliberately neutral so the content
/// remains the source of warmth.
class JiYiAmbientHero extends StatelessWidget {
  const JiYiAmbientHero({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dark = theme.brightness == Brightness.dark;
    return ClipRRect(
      borderRadius: BorderRadius.circular(JiYiRadius.large),
      child: DecoratedBox(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: dark
                ? [
                    JiYiProductColors.darkSurfaceElevated,
                    JiYiProductColors.darkSurface,
                    const Color(0xFF123B5D),
                  ]
                : [
                    theme.colorScheme.surface,
                    JiYiProductColors.surfaceSoft,
                    const Color(0xFFE5EFFB),
                  ],
          ),
          border: Border.all(color: theme.colorScheme.outlineVariant),
          boxShadow: dark
              ? null
              : const [
                  BoxShadow(
                    color: Color(0x0C14233A),
                    blurRadius: 20,
                    offset: Offset(0, 8),
                  ),
                ],
        ),
        child: Stack(
          children: [
            Positioned(
              top: -42,
              right: -26,
              child: _AmbientOrb(
                size: 128,
                color: theme.colorScheme.primary.withValues(alpha: 0.10),
              ),
            ),
            Positioned(
              bottom: -54,
              left: -30,
              child: _AmbientOrb(
                size: 150,
                color: theme.colorScheme.secondary.withValues(alpha: 0.08),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(JiYiSpacing.lg),
              child: child,
            ),
          ],
        ),
      ),
    );
  }
}

class _AmbientOrb extends StatelessWidget {
  const _AmbientOrb({required this.size, required this.color});

  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(shape: BoxShape.circle, color: color),
      ),
    );
  }
}

// 保留这个轻量兼容入口，供仍引用共享 Hero API 的模块平滑迁移。
// 新页面优先使用 JiYiPageFrame 的中性标题系统，不再使用氛围插画或暖色背景。
class JiYiHeroHeader extends StatelessWidget {
  const JiYiHeroHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.eyebrow,
    this.trailing,
  });

  final String title;
  final String? subtitle;
  final String? eyebrow;
  final Widget? trailing;

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
        padding: const EdgeInsets.all(JiYiSpacing.lg),
        child: _JiYiPageTitle(
          title: title,
          subtitle: subtitle,
          eyebrow: eyebrow,
          trailing: trailing,
        ),
      ),
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
        boxShadow: theme.brightness == Brightness.dark
            ? null
            : const [
                BoxShadow(
                  color: Color(0x0A14233A),
                  blurRadius: 14,
                  offset: Offset(0, 4),
                ),
              ],
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
                    _SectionLeading(child: leading!),
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

// The cobalt rule is the visual signature of a screen: it gives every page a
// shared reading edge without inventing a second, decorative hero layer.
class _JiYiPageTitle extends StatelessWidget {
  const _JiYiPageTitle({
    required this.title,
    this.subtitle,
    this.eyebrow,
    this.trailing,
  });

  final String title;
  final String? subtitle;
  final String? eyebrow;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
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
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.5,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.xs),
              ],
              Semantics(
                header: true,
                child: Text(
                  title,
                  style: (eyebrow == null
                          ? theme.textTheme.headlineSmall
                          : theme.textTheme.displaySmall)
                      ?.copyWith(
                    fontSize: eyebrow == null ? 32 : 34,
                    height: 1.15,
                    fontWeight: FontWeight.w800,
                    letterSpacing: eyebrow == null ? -0.45 : -0.9,
                  ),
                ),
              ),
              if (subtitle != null) ...[
                const SizedBox(height: JiYiSpacing.xs),
                Text(
                  subtitle!,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                    height: 1.45,
                  ),
                ),
              ],
            ],
          ),
        ),
        if (trailing != null) ...[
          const SizedBox(width: JiYiSpacing.md),
          trailing!,
        ],
      ],
    );
  }
}

class _SectionLeading extends StatelessWidget {
  const _SectionLeading({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (child is! Icon) return child;
    final theme = Theme.of(context);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(JiYiRadius.control),
      ),
      child: SizedBox.square(
        dimension: 36,
        child: Center(child: child),
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
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 8,
                height: 8,
                margin: const EdgeInsets.only(top: 8),
                decoration: BoxDecoration(
                  color: theme.colorScheme.primary,
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: JiYiSpacing.xs),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: theme.textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w800,
                        letterSpacing: -0.2,
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
      elevation: theme.brightness == Brightness.dark ? 0 : 1,
      shadowColor: const Color(0x0F14233A),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        side: BorderSide(color: theme.colorScheme.outlineVariant),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(JiYiSpacing.md),
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

class JiYiMetric {
  const JiYiMetric({
    required this.icon,
    required this.value,
    required this.label,
  });

  final IconData icon;
  final String value;
  final String label;
}

// MetricStrip only lays out values already supplied by the caller. It never
// calculates counts or turns missing data into a dashboard statistic.
class JiYiMetricStrip extends StatelessWidget {
  const JiYiMetricStrip({
    super.key,
    required this.metrics,
  });

  final List<JiYiMetric> metrics;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        for (var index = 0; index < metrics.length; index++) ...[
          Expanded(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  metrics[index].icon,
                  size: JiYiIconSize.small,
                  color: theme.colorScheme.primary,
                ),
                const SizedBox(height: JiYiSpacing.xxs),
                Text(
                  metrics[index].value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.xxs),
                Text(
                  metrics[index].label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          if (index != metrics.length - 1)
            Container(
              width: 1,
              height: 46,
              color: theme.colorScheme.outlineVariant,
            ),
        ],
      ],
    );
  }
}
