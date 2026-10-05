import 'package:flutter/material.dart';

import '../api_client.dart';
import '../media_presentation_cache.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';
import 'life_events_page.dart';
import 'life_history_page.dart';
import 'life_stages_page.dart';
import 'memoirs_page.dart';

class LifePage extends StatelessWidget {
  const LifePage({
    super.key,
    required this.api,
    this.mediaCache,
  });

  final JiYiApiClient api;
  final LocalMediaCache? mediaCache;

  @override
  Widget build(BuildContext context) {
    return JiYiPageFrame(
      title: '我的人生',
      subtitle: '把重要经历、人生阶段和跨年的故事慢慢整理在一起。',
      eyebrow: '迹忆',
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 520;
          final width = compact
              ? constraints.maxWidth
              : (constraints.maxWidth - JiYiSpacing.md) / 2;
          final entries = [
            _Entry(
              icon: Icons.event_note_outlined,
              title: '人生经历',
              message: '整理重要经历，并关联你亲自确认的记录。',
              onTap: () => Navigator.of(context).push<void>(
                MaterialPageRoute(builder: (_) => LifeEventsPage(api: api)),
              ),
            ),
            _Entry(
              icon: Icons.view_timeline_outlined,
              title: '人生阶段',
              message: '把经历放进人生阶段，再慢慢补全。',
              onTap: () => Navigator.of(context).push<void>(
                MaterialPageRoute(builder: (_) => LifeStagesPage(api: api)),
              ),
            ),
            _Entry(
              icon: Icons.history_outlined,
              title: '多年时间线',
              message: '按时间回看跨年的重要经历与阶段。',
              onTap: () => Navigator.of(context).push<void>(
                MaterialPageRoute(builder: (_) => LifeHistoryPage(api: api)),
              ),
            ),
            _Entry(
              icon: Icons.auto_stories_outlined,
              title: '人生故事',
              message: '用保存的记录回看年度与人生章节。',
              onTap: () => Navigator.of(context).push<void>(
                MaterialPageRoute(
                  builder: (_) => MemoirsPage(
                    api: api,
                    mediaCache: mediaCache,
                  ),
                ),
              ),
            ),
          ];
          return Wrap(
            spacing: JiYiSpacing.md,
            runSpacing: JiYiSpacing.md,
            children: [
              for (final entry in entries) SizedBox(width: width, child: entry),
            ],
          );
        },
      ),
    );
  }
}

class _Entry extends StatelessWidget {
  const _Entry({
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
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        side: BorderSide(color: theme.colorScheme.outlineVariant),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 168),
          child: Padding(
            padding: const EdgeInsets.all(JiYiSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                DecoratedBox(
                  decoration: BoxDecoration(
                    color: theme.colorScheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(JiYiRadius.control),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(JiYiSpacing.sm),
                    child: Icon(icon, color: theme.colorScheme.primary),
                  ),
                ),
                const SizedBox(height: JiYiSpacing.md),
                Container(
                  width: 28,
                  height: 3,
                  decoration: BoxDecoration(
                    color: theme.colorScheme.primary,
                    borderRadius: BorderRadius.circular(JiYiRadius.pill),
                  ),
                ),
                const SizedBox(height: JiYiSpacing.md),
                Text(
                  title,
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.xs),
                Text(
                  message,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                    height: 1.45,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
