import 'dart:async';

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../media_presentation_cache.dart';
import '../ui/jiyi_tokens.dart';
import '../ui/jiyi_v3_components.dart';
import 'life_events_page.dart';
import 'life_history_page.dart';
import 'life_stages_page.dart';
import 'memoirs_page.dart';
import 'v2_authority.dart';

/// Batch 5A Life home.
///
/// This page is intentionally a presentation shell. The four cards only route
/// to existing, server-authoritative V2 pages; no life statistics, memories,
/// relationships, or photos are inferred here.
class LifePage extends StatefulWidget {
  const LifePage({
    super.key,
    required this.api,
    this.mediaCache,
  });

  final JiYiApiClient api;
  final LocalMediaCache? mediaCache;

  @override
  State<LifePage> createState() => _LifePageState();
}

class _LifePageState extends State<LifePage> {
  final V2Authority _navigationAuthority = V2Authority();
  bool _navigationInFlight = false;

  @override
  void didUpdateWidget(covariant LifePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.api, widget.api)) {
      _navigationAuthority.invalidate();
    }
  }

  @override
  void dispose() {
    _navigationAuthority.invalidate();
    super.dispose();
  }

  void _openRoute({
    required String identity,
    required Widget Function() builder,
  }) {
    if (_navigationInFlight) return;

    V2AuthoritySnapshot? snapshot;
    try {
      snapshot = _navigationAuthority.capture(widget.api, identity);
    } catch (_) {
      return;
    }

    _navigationInFlight = true;
    scheduleMicrotask(() {
      final captured = snapshot;
      if (!mounted ||
          captured == null ||
          !_navigationAuthority.isCurrent(widget.api, captured, identity)) {
        if (mounted) setState(() => _navigationInFlight = false);
        return;
      }

      Navigator.of(context)
          .push<void>(
            MaterialPageRoute<void>(
              builder: (_) {
                if (!_navigationAuthority.isCurrent(
                  widget.api,
                  captured,
                  identity,
                )) {
                  return const _LifeRebindSurface();
                }
                return builder();
              },
            ),
          )
          .whenComplete(() {
            if (mounted) setState(() => _navigationInFlight = false);
          });
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return V3PageScaffold(
      backgroundColor: theme.scaffoldBackgroundColor,
      topBar: const _LifeHeader(),
      padding: const EdgeInsets.fromLTRB(
        JiYiSpacing.pageHorizontalPadding,
        JiYiSpacing.xs,
        JiYiSpacing.pageHorizontalPadding,
        JiYiSpacing.xxl,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _LifeHero(),
          const SizedBox(height: JiYiSpacing.xl),
          _EntryGrid(
            onOpenEvents: () => _openRoute(
              identity: 'life-events',
              builder: () => LifeEventsPage(api: widget.api),
            ),
            onOpenStages: () => _openRoute(
              identity: 'life-stages',
              builder: () => LifeStagesPage(api: widget.api),
            ),
            onOpenHistory: () => _openRoute(
              identity: 'life-history',
              builder: () => LifeHistoryPage(api: widget.api),
            ),
            onOpenMemoirs: () => _openRoute(
              identity: 'memoirs',
              builder: () => MemoirsPage(
                api: widget.api,
                mediaCache: widget.mediaCache,
              ),
            ),
          ),
          const SizedBox(height: JiYiSpacing.xl),
          V3SurfaceCard(
            key: const ValueKey('life-home-recent-section'),
            padding: const EdgeInsets.all(JiYiSpacing.lg),
            color: theme.colorScheme.surface,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '继续整理',
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: theme.colorScheme.onSurface,
                    fontSize: JiYiTypography.titleSection,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.sm),
                Text(
                  '打开人生经历，回看并整理自己记录的故事。',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                    fontSize: JiYiTypography.bodyPrimary,
                    height: 1.45,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.md),
                OutlinedButton.icon(
                  key: const ValueKey('life-home-create-event'),
                  onPressed: () => _openRoute(
                    identity: 'life-events',
                    builder: () => LifeEventsPage(api: widget.api),
                  ),
                  icon: const Icon(Icons.add),
                  label: const Text('查看人生经历'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _LifeHeader extends StatelessWidget {
  const _LifeHeader();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        JiYiSpacing.pageHorizontalPadding,
        JiYiSpacing.md,
        JiYiSpacing.pageHorizontalPadding,
        JiYiSpacing.xs,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '我的人生',
            semanticsLabel: '我的人生',
            style: theme.textTheme.headlineSmall?.copyWith(
              color: theme.colorScheme.onSurface,
              fontSize: 30,
              fontWeight: FontWeight.w700,
              height: 1.15,
            ),
          ),
          const SizedBox(height: JiYiSpacing.xs),
          Text(
            '把重要经历和人生阶段，慢慢整理在一起',
            style: theme.textTheme.bodyLarge?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
              fontSize: JiYiTypography.bodyPrimary,
              height: 1.35,
            ),
          ),
        ],
      ),
    );
  }
}

class _LifeHero extends StatelessWidget {
  const _LifeHero();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final heroTextColor = isDark
        ? theme.colorScheme.onSurface
        : JiYiTodayVisuals.navy;
    return Semantics(
      container: true,
      label: '回看、整理、珍藏。人生经历入口。',
      child: ClipRRect(
        borderRadius: BorderRadius.circular(JiYiRadius.large),
        child: SizedBox(
          height: 154,
          child: Stack(
            fit: StackFit.expand,
            children: [
              Image.asset(
                'assets/brand/today_hero_default.png',
                fit: BoxFit.cover,
                alignment: Alignment.center,
                errorBuilder: (context, error, stackTrace) =>
                    DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [
                        theme.colorScheme.primaryContainer,
                        theme.colorScheme.surface,
                      ],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
                  ),
                ),
              ),
              DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [
                      (isDark ? theme.colorScheme.surface : Colors.white)
                          .withValues(alpha: isDark ? 0.90 : 0.88),
                      (isDark ? theme.colorScheme.surface : Colors.white)
                          .withValues(alpha: isDark ? 0.35 : 0.22),
                      Colors.transparent,
                    ],
                    begin: Alignment.centerLeft,
                    end: Alignment.centerRight,
                  ),
                ),
              ),
              Positioned(
                left: JiYiSpacing.lg,
                top: JiYiSpacing.lg,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 200),
                  child: Text(
                    '回看、整理、珍藏',
                    style: theme.textTheme.titleLarge?.copyWith(
                      color: heroTextColor,
                      fontSize: 24,
                      fontWeight: FontWeight.w700,
                      height: 1.2,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EntryGrid extends StatelessWidget {
  const _EntryGrid({
    required this.onOpenEvents,
    required this.onOpenStages,
    required this.onOpenHistory,
    required this.onOpenMemoirs,
  });

  final VoidCallback onOpenEvents;
  final VoidCallback onOpenStages;
  final VoidCallback onOpenHistory;
  final VoidCallback onOpenMemoirs;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (_, __) {
        return Column(
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: _LifeEntryCard(
                    key: const ValueKey('life-home-entry-events'),
                    icon: Icons.event_note_outlined,
                    title: '人生经历',
                    message: '留下重要的节点',
                    onTap: onOpenEvents,
                  ),
                ),
                const SizedBox(width: JiYiSpacing.sm),
                Expanded(
                  child: _LifeEntryCard(
                    key: const ValueKey('life-home-entry-stages'),
                    icon: Icons.view_timeline_outlined,
                    title: '人生阶段',
                    message: '把一段时光放在一起',
                    onTap: onOpenStages,
                  ),
                ),
              ],
            ),
            const SizedBox(height: JiYiSpacing.sm),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: _LifeEntryCard(
                    key: const ValueKey('life-home-entry-history'),
                    icon: Icons.history_outlined,
                    title: '多年时间线',
                    message: '主动回看这些年',
                    onTap: onOpenHistory,
                  ),
                ),
                const SizedBox(width: JiYiSpacing.sm),
                Expanded(
                  child: _LifeEntryCard(
                    key: const ValueKey('life-home-entry-memoirs'),
                    icon: Icons.auto_stories_outlined,
                    title: '人生故事',
                    message: '需要时再整理成故事',
                    onTap: onOpenMemoirs,
                  ),
                ),
              ],
            ),
          ],
        );
      },
    );
  }
}

class _LifeEntryCard extends StatelessWidget {
  const _LifeEntryCard({
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
    return V3SurfaceCard(
      semanticLabel: title,
      padding: const EdgeInsets.all(JiYiSpacing.md),
      borderRadius: BorderRadius.circular(JiYiRadius.large),
      color: theme.colorScheme.surface,
      onTap: onTap,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 154),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              icon,
              size: JiYiIconSize.medium,
              color: theme.colorScheme.primary,
              semanticLabel: '$title 图标',
            ),
            const SizedBox(height: JiYiSpacing.xl),
            Text(
              title,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.titleMedium?.copyWith(
                color: theme.colorScheme.onSurface,
                fontSize: JiYiTypography.titleSection,
                fontWeight: FontWeight.w700,
                height: 1.25,
              ),
            ),
            const SizedBox(height: JiYiSpacing.xs),
            Text(
              message,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
                fontSize: JiYiTypography.bodySecondary,
                height: 1.35,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _LifeRebindSurface extends StatelessWidget {
  const _LifeRebindSurface();

  @override
  Widget build(BuildContext context) {
    return const V3PageScaffold(
      title: '我的人生',
      child: V3StateSurface(
        variant: V3StateSurfaceVariant.blocked,
        title: '会话已变化',
        message: '当前页面已停止旧账号操作，请返回后重新打开。',
        semanticsLabel: '会话已变化：当前页面已停止旧账号操作，请返回后重新打开。',
      ),
    );
  }
}
