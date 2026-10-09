import 'package:flutter/material.dart';

import 'jiyi_tokens.dart';

/// Shared V3 page container. It owns layout seams only; feature state,
/// navigation authority, and API/session work remain with the caller.
class V3PageScaffold extends StatelessWidget {
  const V3PageScaffold({
    super.key,
    required this.child,
    this.title,
    this.subtitle,
    this.topBar,
    this.scrollable = true,
    this.padding,
    this.backgroundColor,
    this.includeBottomSafeArea = false,
    this.maxContentWidth = 720,
    this.resizeToAvoidBottomInset = true,
  });

  final Widget child;
  final String? title;
  final String? subtitle;
  final Widget? topBar;
  final bool scrollable;
  final EdgeInsetsGeometry? padding;
  final Color? backgroundColor;
  final bool includeBottomSafeArea;
  final double maxContentWidth;
  final bool resizeToAvoidBottomInset;

  @override
  Widget build(BuildContext context) {
    final resolvedTopBar = topBar ??
        (title == null
            ? null
            : V3TopBar(title: title!, subtitle: subtitle));
    final resolvedPadding = padding ??
        const EdgeInsets.symmetric(
          horizontal: JiYiSpacing.pageHorizontalPadding,
          vertical: JiYiSpacing.md,
        );

    return Scaffold(
      backgroundColor: backgroundColor ?? JiYiSurfaceRoles.pageBackground,
      resizeToAvoidBottomInset: resizeToAvoidBottomInset,
      body: SafeArea(
        top: true,
        bottom: includeBottomSafeArea,
        child: Column(
          children: [
            if (resolvedTopBar != null) resolvedTopBar,
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final content = scrollable
                      ? SingleChildScrollView(
                          padding: resolvedPadding,
                          child: child,
                        )
                      : Padding(padding: resolvedPadding, child: child);
                  return Align(
                    alignment: Alignment.topCenter,
                    child: ConstrainedBox(
                      constraints: BoxConstraints(
                        maxWidth: maxContentWidth,
                        minWidth: constraints.maxWidth < maxContentWidth
                            ? constraints.maxWidth
                            : 0,
                      ),
                      child: content,
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Shared V3 top bar. It does not push routes or infer navigation behavior.
class V3TopBar extends StatelessWidget {
  const V3TopBar({
    super.key,
    required this.title,
    this.subtitle,
    this.onBack,
    this.backLabel = '返回',
    this.leading,
    this.trailing,
  });

  final String title;
  final String? subtitle;
  final VoidCallback? onBack;
  final String backLabel;
  final Widget? leading;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final leadingWidget = leading ??
        (onBack == null
            ? const SizedBox.square(dimension: JiYiTapTarget.normal)
            : Semantics(
                button: true,
                label: backLabel,
                onTap: onBack,
                child: ExcludeSemantics(
                  child: IconButton(
                    onPressed: onBack,
                    icon: const Icon(Icons.arrow_back_ios_new),
                    tooltip: backLabel,
                    constraints: const BoxConstraints(
                      minWidth: JiYiTapTarget.normal,
                      minHeight: JiYiTapTarget.normal,
                    ),
                  ),
                ),
              ));

    return Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: JiYiSpacing.cardPadding,
        vertical: JiYiSpacing.xs,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          leadingWidget,
          const SizedBox(width: JiYiSpacing.xs),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleLarge?.copyWith(
                    fontSize: JiYiTypography.titleLarge,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                if (subtitle != null)
                  Text(
                    subtitle!,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      fontSize: JiYiTypography.bodySecondary,
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
              ],
            ),
          ),
          if (trailing != null) ...[
            const SizedBox(width: JiYiSpacing.xs),
            Flexible(
              fit: FlexFit.loose,
              child: Align(alignment: Alignment.centerRight, child: trailing),
            ),
          ],
        ],
      ),
    );
  }
}

/// Shared elevated surface. Today pages may continue using their locked card
/// implementation; this primitive is opt-in for later V3 migrations.
class V3SurfaceCard extends StatelessWidget {
  const V3SurfaceCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(JiYiSpacing.cardPadding),
    this.color,
    this.borderColor,
    this.borderRadius,
    this.elevation = 0,
    this.shadowColor,
    this.onTap,
    this.semanticLabel,
    this.clipBehavior = Clip.antiAlias,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final Color? color;
  final Color? borderColor;
  final BorderRadius? borderRadius;
  final double elevation;
  final Color? shadowColor;
  final VoidCallback? onTap;
  final String? semanticLabel;
  final Clip clipBehavior;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final radius = borderRadius ??
        BorderRadius.circular(JiYiRadius.surfaceRadius);
    final shape = RoundedRectangleBorder(
      borderRadius: radius,
      side: BorderSide(
        color: borderColor ?? JiYiSurfaceRoles.border,
      ),
    );

    final content = Padding(padding: padding, child: child);
    final surface = Material(
      color: color ?? theme.colorScheme.surface,
      elevation: elevation,
      shadowColor: shadowColor,
      shape: shape,
      clipBehavior: clipBehavior,
      child: onTap == null
          ? content
          : InkWell(
              onTap: onTap,
              child: ConstrainedBox(
                constraints: const BoxConstraints(
                  minHeight: JiYiTapTarget.normal,
                ),
                child: content,
              ),
            ),
    );

    if (onTap == null) {
      return Semantics(label: semanticLabel, child: surface);
    }

    return Semantics(
      container: true,
      button: true,
      label: semanticLabel,
      onTap: onTap,
      child: ExcludeSemantics(child: surface),
    );
  }
}

/// Shared section title/action layout. The title remains flexible so actions
/// stay reachable at narrow widths and large text scales.
class V3SectionHeader extends StatelessWidget {
  const V3SectionHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.trailing,
    this.count,
  });

  final String title;
  final String? subtitle;
  final Widget? trailing;
  final int? count;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Expanded(
              child: Text(
                count == null ? title : '$title（$count）',
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.titleMedium?.copyWith(
                  fontSize: JiYiTypography.titleSection,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            if (trailing != null) ...[
              const SizedBox(width: JiYiSpacing.xs),
              Flexible(
                fit: FlexFit.loose,
                child: Align(
                  alignment: Alignment.centerRight,
                  child: trailing,
                ),
              ),
            ],
          ],
        ),
        if (subtitle != null) ...[
          const SizedBox(height: JiYiSpacing.xxs),
          Text(
            subtitle!,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: theme.textTheme.bodyMedium?.copyWith(
              fontSize: JiYiTypography.bodySecondary,
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ],
    );
  }
}

enum V3StateSurfaceVariant { loading, empty, error, offline, blocked }

class V3StateAction {
  const V3StateAction({
    required this.label,
    required this.onPressed,
    this.icon,
  });

  final String label;
  final VoidCallback onPressed;
  final IconData? icon;
}

/// Shared state presentation. The variant is explicit so loading, empty,
/// error, offline, and blocked cannot be collapsed into one visual state.
class V3StateSurface extends StatelessWidget {
  const V3StateSurface({
    super.key,
    required this.variant,
    required this.title,
    required this.message,
    this.icon,
    this.primaryAction,
    this.secondaryAction,
    this.semanticsLabel,
  });

  final V3StateSurfaceVariant variant;
  final String title;
  final String message;
  final IconData? icon;
  final V3StateAction? primaryAction;
  final V3StateAction? secondaryAction;
  final String? semanticsLabel;

  IconData get _defaultIcon {
    switch (variant) {
      case V3StateSurfaceVariant.loading:
        return Icons.hourglass_top;
      case V3StateSurfaceVariant.empty:
        return Icons.inbox_outlined;
      case V3StateSurfaceVariant.error:
        return Icons.error_outline;
      case V3StateSurfaceVariant.offline:
        return Icons.cloud_off_outlined;
      case V3StateSurfaceVariant.blocked:
        return Icons.lock_outline;
    }
  }

  String get _variantSemantics {
    switch (variant) {
      case V3StateSurfaceVariant.loading:
        return '正在加载';
      case V3StateSurfaceVariant.empty:
        return '暂无内容';
      case V3StateSurfaceVariant.error:
        return '加载失败';
      case V3StateSurfaceVariant.offline:
        return '当前离线';
      case V3StateSurfaceVariant.blocked:
        return '暂不可用';
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final actions = <Widget>[
      if (primaryAction != null)
        FilledButton.icon(
          onPressed: primaryAction!.onPressed,
          icon: Icon(primaryAction!.icon ?? Icons.arrow_forward),
          label: Text(primaryAction!.label),
        ),
      if (secondaryAction != null)
        TextButton.icon(
          onPressed: secondaryAction!.onPressed,
          icon: Icon(secondaryAction!.icon ?? Icons.more_horiz),
          label: Text(secondaryAction!.label),
        ),
    ];

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: JiYiSpacing.xl),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Semantics(
            container: true,
            liveRegion: variant == V3StateSurfaceVariant.loading,
            label: semanticsLabel ?? '$_variantSemantics：$title。$message',
            child: ExcludeSemantics(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    icon ?? _defaultIcon,
                    size: JiYiIconSize.large,
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                  const SizedBox(height: JiYiSpacing.sm),
                  Text(
                    title,
                    textAlign: TextAlign.center,
                    style: theme.textTheme.titleMedium?.copyWith(
                      fontSize: JiYiTypography.titleSection,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: JiYiSpacing.xs),
                  Text(
                    message,
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      fontSize: JiYiTypography.bodySecondary,
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (actions.isNotEmpty) ...[
            const SizedBox(height: JiYiSpacing.md),
            Wrap(
              alignment: WrapAlignment.center,
              spacing: JiYiSpacing.sm,
              runSpacing: JiYiSpacing.xs,
              children: actions,
            ),
          ],
        ],
      ),
    );
  }
}
