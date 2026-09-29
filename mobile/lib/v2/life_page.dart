import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';
import 'life_events_page.dart';
import 'life_history_page.dart';
import 'life_stages_page.dart';
import 'memoirs_page.dart';

class LifePage extends StatelessWidget {
  const LifePage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  Widget build(BuildContext context) {
    return JiYiPageFrame(
      title: '我的人生',
      subtitle: '把重要经历、人生阶段和跨年的故事慢慢整理在一起。',
      hero: const JiYiHeroHeader(
        eyebrow: '迹忆 · 人生',
        title: '我的人生',
        subtitle: '把重要经历、人生阶段和跨年的故事慢慢整理在一起；AI 只在你主动回顾时参与。',
        icon: Icons.auto_stories_outlined,
      ),
      child: Column(
        children: [
          _Entry(
            icon: Icons.event_note_outlined,
            title: '人生经历',
            message: '整理重要经历，并关联你亲自确认的相关记录。',
            onTap: () => Navigator.of(context).push<void>(
              MaterialPageRoute(builder: (_) => LifeEventsPage(api: api)),
            ),
          ),
          const SizedBox(height: JiYiSpacing.sm),
          _Entry(
            icon: Icons.view_timeline_outlined,
            title: '人生阶段',
            message: '整理人生阶段与重要经历之间的关系，需要时再生成长期回顾。',
            onTap: () => Navigator.of(context).push<void>(
              MaterialPageRoute(builder: (_) => LifeStagesPage(api: api)),
            ),
          ),
          const SizedBox(height: JiYiSpacing.sm),
          _Entry(
            icon: Icons.history_outlined,
            title: '多年时间线',
            message: '按时间回看跨年的重要经历和人生阶段。',
            onTap: () => Navigator.of(context).push<void>(
              MaterialPageRoute(builder: (_) => LifeHistoryPage(api: api)),
            ),
          ),
          const SizedBox(height: JiYiSpacing.sm),
          _Entry(
            icon: Icons.auto_stories_outlined,
            title: '人生故事',
            message: '查看年度回顾，也可以按人生阶段生成故事章节。',
            onTap: () => Navigator.of(context).push<void>(
              MaterialPageRoute(builder: (_) => MemoirsPage(api: api)),
            ),
          ),
        ],
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
    return JiYiActionCard(
      icon: icon,
      title: title,
      message: message,
      onTap: onTap,
    );
  }
}
