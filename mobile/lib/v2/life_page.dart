import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';
import 'v2_widgets.dart';
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
      title: '人生',
      subtitle: '整理明确的人生事件和阶段；AI 回顾只在你主动点击后生成。',
      child: Column(
        children: [
          _Entry(
            icon: Icons.event_note_outlined,
            title: '人生事件',
            message: 'CRUD、地点选择和显式 Memory 证据关联。',
            onTap: () => Navigator.of(context).push<void>(
              MaterialPageRoute(builder: (_) => LifeEventsPage(api: api)),
            ),
          ),
          const SizedBox(height: JiYiSpacing.sm),
          _Entry(
            icon: Icons.view_timeline_outlined,
            title: '人生阶段',
            message: 'CRUD、LifeEvent 显式关联和 evidence-backed 长期回顾。',
            onTap: () => Navigator.of(context).push<void>(
              MaterialPageRoute(builder: (_) => LifeStagesPage(api: api)),
            ),
          ),
          const SizedBox(height: JiYiSpacing.sm),
          _Entry(
            icon: Icons.history_outlined,
            title: '跨年时间线',
            message: '按服务端确定性投影跨年份浏览，游标原样续传。',
            onTap: () => Navigator.of(context).push<void>(
              MaterialPageRoute(builder: (_) => LifeHistoryPage(api: api)),
            ),
          ),
          const SizedBox(height: JiYiSpacing.sm),
          _Entry(
            icon: Icons.auto_stories_outlined,
            title: '回忆录',
            message: '年度电子回忆录和按人生阶段生成的人生回忆录。',
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
    return V2SectionCard(
      leading: Icon(icon),
      title: title,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(message),
          const SizedBox(height: JiYiSpacing.sm),
          OutlinedButton(
            onPressed: onTap,
            child: const Text('打开'),
          ),
        ],
      ),
    );
  }
}
