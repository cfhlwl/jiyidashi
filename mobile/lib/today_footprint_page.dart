import 'package:flutter/material.dart';

import 'amap_footprint_map.dart';
import 'amap_privacy_consent.dart';
import 'api_client.dart';
import 'memory_detail_page.dart';
import 'media_presentation_cache.dart';
import 'footprint_detail_page.dart';
import 'footprint_models.dart';
import 'timeline_models.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_format.dart';
import 'ui/jiyi_tokens.dart';

// Today Footprint 是服务端按账号时区和 Visit overlap 生成的权威只读投影。
// Flutter 只做严格协议解析与展示；网络/协议失败时 fail closed，不用设备当前位置或客户端猜测补足“今天”。
class TodayPage extends StatefulWidget {
  const TodayPage({
    super.key,
    required this.api,
    this.elderMode = false,
    this.onCapture,
    this.onOpenFamily,
    this.mediaCache,
    this.photoThumbnailBuilder,
    this.amapPrivacyConsent,
  });

  final JiYiApiClient api;
  final bool elderMode;
  final VoidCallback? onCapture;
  final VoidCallback? onOpenFamily;
  final LocalMediaCache? mediaCache;
  final LocalMediaThumbnailBuilder? photoThumbnailBuilder;
  final AmapPrivacyConsentAuthority? amapPrivacyConsent;

  @override
  State<TodayPage> createState() => _TodayPageState();
}

class _TodayPageState extends State<TodayPage> {
  Map<String, dynamic>? _data;
  List<TimelineReadItem> _todayMemories = const [];
  bool _memoryUnavailable = false;
  Object? _error;
  bool _loading = true;
  int _generation = 0;
  late final AmapPrivacyConsentAuthority _amapPrivacyConsent;
  bool _mapPrivacyAccepted = false;

  @override
  void initState() {
    super.initState();
    _amapPrivacyConsent =
        widget.amapPrivacyConsent ?? AmapPrivacyConsentStore();
    _loadMapPrivacy();
    _load();
  }

  Future<void> _loadMapPrivacy() async {
    try {
      final accepted = await _amapPrivacyConsent.readAccepted();
      if (mounted) setState(() => _mapPrivacyAccepted = accepted);
    } catch (_) {
      if (mounted) setState(() => _mapPrivacyAccepted = false);
    }
  }

  Future<void> _acceptMapPrivacy() async {
    final accepted =
        await requestAmapPrivacyConsent(context, _amapPrivacyConsent);
    if (mounted && accepted) setState(() => _mapPrivacyAccepted = true);
  }

  @override
  void didUpdateWidget(covariant TodayPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api != widget.api) {
      _load();
    }
  }

  @override
  void dispose() {
    _generation += 1;
    super.dispose();
  }

  Future<void> _load() async {
    final generation = ++_generation;
    final sessionVersion = widget.api.sessionVersion;
    final owner = widget.api.authenticatedUserId;
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
        _data = null;
        _todayMemories = const [];
        _memoryUnavailable = false;
      });
    }
    bool current() =>
        mounted &&
        generation == _generation &&
        sessionVersion == widget.api.sessionVersion &&
        owner == widget.api.authenticatedUserId;
    try {
      final data = await widget.api.getTodayFootprint();
      if (!current()) return;

      // Validate Today first. Malformed authority stays a protocol fail-closed
      // state; secondary reads must never reclassify it as a network failure.
      late final FootprintDay footprint;
      try {
        footprint = FootprintDay.fromJson(data);
      } catch (_) {
        if (!current()) return;
        setState(() => _data = data);
        return;
      }

      List<TimelineReadItem> memories = const [];
      var memoryUnavailable = false;
      try {
        final timelineRaw = await widget.api.getTimelineEvents(
          limit: 8,
          day: footprint.day,
        );
        if (!current()) return;
        final timeline = TimelineReadPage.parse(timelineRaw);
        memories = List.unmodifiable(
          timeline.items.where((item) => item.isMemory).take(4),
        );
      } catch (_) {
        if (!current()) return;
        memoryUnavailable = true;
      }

      setState(() {
        _data = data;
        _todayMemories = memories;
        _memoryUnavailable = memoryUnavailable;
      });
    } catch (error) {
      if (!current()) return;
      setState(() => _error = error);
    } finally {
      if (current()) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final elderMode = widget.elderMode;
    return JiYiPageFrame(
      title: elderMode ? '今天去了哪里' : '今天',
      subtitle: elderMode
          ? '这里只显示已经形成的足迹，不会用当前位置猜测。'
          : '看看今天留下了哪些值得记住的片段。',
      hero: _TodayMasthead(
        title: elderMode ? '今天去了哪里' : '今天',
        date: _todayHeroSubtitle(_data),
      ),
      child: _buildContent(elderMode),
    );
  }

  Widget _buildContent(bool elderMode) {
    if (_loading) {
      return const JiYiSectionCard(
        child: Padding(
          key: ValueKey('today-footprint-loading'),
          padding: EdgeInsets.symmetric(vertical: JiYiSpacing.lg),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              SizedBox.square(
                dimension: 20,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
              SizedBox(width: JiYiSpacing.sm),
              Text('正在整理今天的足迹…'),
            ],
          ),
        ),
      );
    }

    if (_error != null) {
      return Column(
        key: const ValueKey('today-footprint-error'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const JiYiStatusBanner(
            kind: JiYiStatusKind.error,
            title: '无法读取今日足迹',
            message: '当前没有读取到可靠的足迹结果，请检查网络后重试。',
          ),
          const SizedBox(height: JiYiSpacing.md),
          OutlinedButton.icon(
            key: const ValueKey('today-footprint-retry'),
            onPressed: _load,
            icon: const Icon(Icons.refresh),
            label: const Text('重新加载'),
          ),
        ],
      );
    }

    late final FootprintDay footprint;
    try {
      footprint = FootprintDay.fromJson(_data!);
    } on Object {
      return Column(
        key: const ValueKey('today-footprint-protocol-error'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const JiYiStatusBanner(
            kind: JiYiStatusKind.error,
            title: '今日足迹数据异常',
            message: '这次足迹数据不完整，已停止展示，避免把未知信息当成真实足迹。',
          ),
          const SizedBox(height: JiYiSpacing.md),
          OutlinedButton.icon(
            key: const ValueKey('today-footprint-protocol-retry'),
            onPressed: _load,
            icon: const Icon(Icons.refresh),
            label: const Text('重新加载'),
          ),
        ],
      );
    }

    return _TodayExperienceBody(
      api: widget.api,
      footprint: footprint,
      memories: _todayMemories,
      memoryUnavailable: _memoryUnavailable,
      elderMode: elderMode,
      onCapture: widget.onCapture,
      onOpenFamily: widget.onOpenFamily,
      mapPrivacyAccepted: _mapPrivacyAccepted,
      onAcceptMapPrivacy: _acceptMapPrivacy,
      amapPrivacyConsent: _amapPrivacyConsent,
      mediaCache: widget.mediaCache,
      photoThumbnailBuilder: widget.photoThumbnailBuilder,
    );
  }
}

class _TodayExperienceBody extends StatelessWidget {
  const _TodayExperienceBody({
    required this.api,
    required this.footprint,
    required this.memories,
    required this.memoryUnavailable,
    required this.elderMode,
    this.onCapture,
    this.onOpenFamily,
    required this.mapPrivacyAccepted,
    required this.onAcceptMapPrivacy,
    required this.amapPrivacyConsent,
    this.mediaCache,
    this.photoThumbnailBuilder,
  });

  final JiYiApiClient api;
  final FootprintDay footprint;
  final List<TimelineReadItem> memories;
  final bool memoryUnavailable;
  final bool elderMode;
  final VoidCallback? onCapture;
  final VoidCallback? onOpenFamily;
  final bool mapPrivacyAccepted;
  final Future<void> Function() onAcceptMapPrivacy;
  final AmapPrivacyConsentAuthority amapPrivacyConsent;
  final LocalMediaCache? mediaCache;
  final LocalMediaThumbnailBuilder? photoThumbnailBuilder;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _footprintCard(context, theme),
        const SizedBox(height: JiYiSpacing.xl),
        const JiYiSectionHeader(
          title: '今日记忆',
          subtitle: '主动记下的片段，会留在今天。',
        ),
        const SizedBox(height: JiYiSpacing.sm),
        _memorySection(context),
        const SizedBox(height: JiYiSpacing.xl),
        const JiYiSectionHeader(
          title: '快速记录',
          subtitle: '想到就记，不必等到以后。',
        ),
        const SizedBox(height: JiYiSpacing.sm),
        _quickCapture(context),
        const SizedBox(height: JiYiSpacing.xl),
        const JiYiSectionHeader(
          title: '家庭共享',
          subtitle: '只有家人明确授权给你的内容才会被读取。',
        ),
        const SizedBox(height: JiYiSpacing.sm),
        JiYiSectionCard(
          leading: Icon(
            Icons.family_restroom_outlined,
            color: theme.colorScheme.primary,
          ),
          title: '家庭内容按授权显示',
          subtitle: '进入家庭后，只读取家人明确授权给你的内容。',
          child: Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: onOpenFamily,
              icon: const Icon(Icons.arrow_forward),
              label: const Text('查看家庭'),
            ),
          ),
        ),
      ],
    );
  }

  Widget _footprintCard(BuildContext context, ThemeData theme) {
    if (footprint.visits.isEmpty) {
      return JiYiSectionCard(
        key: const ValueKey('today-footprint-empty'),
        leading: Icon(Icons.route_outlined, color: theme.colorScheme.primary),
        title: '今天还没有形成足迹',
        child: JiYiEmptyState(
          icon: Icons.location_off_outlined,
          title: '还没有足迹',
          message: elderMode
              ? '不会用当前位置猜测你去过哪里。'
              : '形成到访后，会在这里按时间留下今天的足迹。',
        ),
      );
    }

    void openFootprintDetail() {
      Navigator.of(context).push<void>(
        MaterialPageRoute<void>(
          builder: (_) => FootprintDetailPage(
            api: api,
            footprint: footprint,
            mapPrivacyAccepted: mapPrivacyAccepted,
            onAcceptMapPrivacy: onAcceptMapPrivacy,
          ),
        ),
      );
    }

    return GestureDetector(
      key: const ValueKey('today-footprint-map-open'),
      behavior: HitTestBehavior.translucent,
      onTap: openFootprintDetail,
      child: JiYiSectionCard(
        key: const ValueKey('today-footprint-loaded'),
        leading: Icon(Icons.route_outlined, color: theme.colorScheme.primary),
        title: '今日足迹',
        subtitle: jiyiDisplayDate(footprint.day),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              '${footprint.visits.length} 个地点片段',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: JiYiSpacing.sm),
            if (mapPrivacyAccepted) ...[
              IgnorePointer(
                child: JiYiFootprintMap(
                  visits: footprint.visits,
                  privacyAccepted: true,
                  selectedIndex: 0,
                  onSelected: (_) {},
                  interactive: false,
                ),
              ),
              const SizedBox(height: JiYiSpacing.md),
            ],
            if (elderMode)
              for (var index = 0; index < footprint.visits.length; index++) ...[
                FootprintVisitRow(
                  visit: footprint.visits[index],
                  elderMode: true,
                ),
                if (index != footprint.visits.length - 1)
                  const Divider(height: JiYiSpacing.lg),
              ]
            else
              Wrap(
                spacing: JiYiSpacing.xs,
                runSpacing: JiYiSpacing.xs,
                children: [
                  for (var index = 0; index < footprint.visits.length; index++)
                    _TodayVisitPill(
                      index: index,
                      visit: footprint.visits[index],
                    ),
                ],
              ),
          ],
        ),
      ),
    );
  }

  Widget _memorySection(BuildContext context) {
    if (memoryUnavailable) {
      return const JiYiSectionCard(
        child: JiYiStatusBanner(
          kind: JiYiStatusKind.warning,
          title: '今日记忆暂时没有整理好',
          message: '足迹仍可正常查看，稍后回来会重新读取今天的记忆。',
        ),
      );
    }
    if (memories.isEmpty) {
      return const JiYiSectionCard(
        child: JiYiEmptyState(
          icon: Icons.auto_stories_outlined,
          title: '今天还没有主动记录',
          message: '记下一句话、一张照片或一段语音后，会从这里开始积累。',
        ),
      );
    }
    Widget card(int index, {required bool compact}) => _TodayMemoryCard(
          api: api,
          item: memories[index],
          compact: compact,
          mediaCache: mediaCache,
          photoThumbnailBuilder: photoThumbnailBuilder,
          onTap: () {
            Navigator.of(context).push<bool>(
              MaterialPageRoute<bool>(
                builder: (_) => MemoryDetailPage(
                  api: api,
                  memoryId: memories[index].id,
                  mediaCache: mediaCache,
                  amapPrivacyConsent: amapPrivacyConsent,
                ),
              ),
            );
          },
        );
    if (elderMode) {
      return Column(
        children: [
          for (var index = 0; index < memories.length; index++) ...[
            card(index, compact: false),
            if (index != memories.length - 1)
              const SizedBox(height: JiYiSpacing.sm),
          ],
        ],
      );
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final twoColumns = constraints.maxWidth >= 340;
        final width = twoColumns
            ? (constraints.maxWidth - JiYiSpacing.sm) / 2
            : constraints.maxWidth;
        return Wrap(
          spacing: JiYiSpacing.sm,
          runSpacing: JiYiSpacing.sm,
          children: [
            for (var index = 0; index < memories.length; index++)
              SizedBox(width: width, child: card(index, compact: twoColumns)),
          ],
        );
      },
    );
  }

  Widget _quickCapture(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 360;
        final actions = [
          (Icons.edit_note_outlined, '写一条', '一句话也可以'),
          (Icons.photo_camera_outlined, '拍一张', '留住眼前的画面'),
          (Icons.mic_none_outlined, '录一段', '先说下来再整理'),
        ];
        return Wrap(
          spacing: JiYiSpacing.sm,
          runSpacing: JiYiSpacing.sm,
          children: [
            for (final action in actions)
              SizedBox(
                width: compact
                    ? constraints.maxWidth
                    : (constraints.maxWidth - JiYiSpacing.sm * 2) / 3,
                child: _TodayQuickAction(
                  icon: action.$1,
                  title: action.$2,
                  subtitle: action.$3,
                  onTap: onCapture,
                ),
              ),
          ],
        );
      },
    );
  }
}

class _TodayMemoryCard extends StatelessWidget {
  const _TodayMemoryCard({
    required this.api,
    required this.item,
    required this.onTap,
    required this.compact,
    this.mediaCache,
    this.photoThumbnailBuilder,
  });

  final JiYiApiClient api;
  final TimelineReadItem item;
  final VoidCallback onTap;
  final bool compact;
  final LocalMediaCache? mediaCache;
  final LocalMediaThumbnailBuilder? photoThumbnailBuilder;

  Widget _photoThumbnail(
    BuildContext context, {
    double width = 88,
    double height = 88,
  }) {
    final mediaId = item.mediaId!;
    final builder = photoThumbnailBuilder;
    if (builder != null) {
      return SizedBox(
        key: ValueKey('today-photo-${item.id}'),
        width: width,
        height: height,
        child: KeyedSubtree(
          key: ValueKey('local-media-ready-$mediaId'),
          child: builder(context, mediaId, BoxFit.cover),
        ),
      );
    }
    return LocalMediaThumbnail(
      key: ValueKey('today-photo-${item.id}'),
      api: api,
      mediaId: mediaId,
      cache: mediaCache,
      width: width,
      height: height,
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final title = item.title ?? _todayMemoryTypeLabel(item.memoryType);
    if (compact) {
      return Material(
        color: theme.colorScheme.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(JiYiRadius.card),
          side: BorderSide(color: theme.colorScheme.outlineVariant),
        ),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(JiYiRadius.card),
          child: Padding(
            padding: const EdgeInsets.all(JiYiSpacing.sm),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (item.memoryType == 'PHOTO' && item.mediaId != null)
                  LayoutBuilder(
                    builder: (context, constraints) => ClipRRect(
                      borderRadius: BorderRadius.circular(JiYiRadius.control),
                      child: _photoThumbnail(
                        context,
                        width: constraints.maxWidth,
                        height: 108,
                      ),
                    ),
                  )
                else
                  DecoratedBox(
                    decoration: BoxDecoration(
                      color: theme.colorScheme.surfaceContainerHighest,
                      borderRadius: BorderRadius.circular(JiYiRadius.control),
                    ),
                    child: Padding(
                      padding: const EdgeInsets.all(JiYiSpacing.sm),
                      child: Icon(
                        _todayMemoryIcon(item.memoryType),
                        color: theme.colorScheme.primary,
                      ),
                    ),
                  ),
                const SizedBox(height: JiYiSpacing.sm),
                Text(
                  title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.xxs),
                Text(
                  jiyiDisplayTime(item.occurredAt),
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }
    return Material(
      color: theme.colorScheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        side: BorderSide(color: theme.colorScheme.outlineVariant),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        child: Padding(
          padding: const EdgeInsets.all(JiYiSpacing.md),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (item.memoryType == 'PHOTO' && item.mediaId != null)
                _photoThumbnail(context)
              else
                DecoratedBox(
                  decoration: BoxDecoration(
                    color: theme.colorScheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(JiYiRadius.control),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(JiYiSpacing.sm),
                    child: Icon(
                      _todayMemoryIcon(item.memoryType),
                      color: theme.colorScheme.primary,
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
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    if (item.content != null && item.content!.trim().isNotEmpty) ...[
                      const SizedBox(height: JiYiSpacing.xs),
                      Text(
                        item.content!,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                    const SizedBox(height: JiYiSpacing.xs),
                    Text(
                      jiyiDisplayTime(item.occurredAt),
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right),
            ],
          ),
        ),
      ),
    );
  }
}

class _TodayMasthead extends StatelessWidget {
  const _TodayMasthead({required this.title, required this.date});

  final String title;
  final String date;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: JiYiSpacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      '迹忆',
                      style: theme.textTheme.labelLarge?.copyWith(
                        color: theme.colorScheme.primary,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.5,
                      ),
                    ),
                    Text(
                      ' · ',
                      style: theme.textTheme.labelLarge?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    Text(
                      '今天好',
                      style: theme.textTheme.labelLarge?.copyWith(
                        color: theme.colorScheme.primary,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.5,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: JiYiSpacing.xs),
                Text(
                  title,
                  style: theme.textTheme.displaySmall?.copyWith(
                    fontWeight: FontWeight.w800,
                    letterSpacing: -1.2,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.xs),
                Text(
                  date,
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ),
          ),
          DecoratedBox(
            decoration: BoxDecoration(
              color: theme.colorScheme.surface,
              borderRadius: BorderRadius.circular(JiYiRadius.pill),
              border: Border.all(color: theme.colorScheme.outlineVariant),
            ),
            child: Padding(
              padding: const EdgeInsets.all(JiYiSpacing.sm),
              child: Icon(
                Icons.calendar_today_outlined,
                color: theme.colorScheme.primary,
                size: JiYiIconSize.medium,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TodayQuickAction extends StatelessWidget {
  const _TodayQuickAction({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback? onTap;

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
          constraints: const BoxConstraints(minHeight: JiYiTapTarget.normal + 56),
          child: Padding(
            padding: const EdgeInsets.all(JiYiSpacing.md),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(icon, color: theme.colorScheme.primary),
                const SizedBox(height: JiYiSpacing.sm),
                Text(
                  title,
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.xxs),
                Text(
                  subtitle,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
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

String _todayMemoryTypeLabel(String? value) => switch (value) {
      'VOICE' => '一段语音记忆',
      'PHOTO' => '一张照片记忆',
      'PLACE' => '一个地点记忆',
      'OBJECT_LOCATION' => '一条物品位置',
      _ => '一段记忆',
    };

IconData _todayMemoryIcon(String? value) => switch (value) {
      'VOICE' => Icons.mic_none_outlined,
      'PHOTO' => Icons.photo_outlined,
      'PLACE' => Icons.place_outlined,
      'OBJECT_LOCATION' => Icons.inventory_2_outlined,
      _ => Icons.auto_stories_outlined,
    };

String _todayHeroSubtitle(Map<String, dynamic>? data) {
  final day = data?['day'];
  if (day is String && isStrictDateOnly(day)) {
    return jiyiDisplayDate(day);
  }
  return '正在整理今天';
}

class _TodayVisitPill extends StatelessWidget {
  const _TodayVisitPill({
    required this.index,
    required this.visit,
  });

  final int index;
  final FootprintVisit visit;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final time = _clock(visit.arrivedAtLocal);
    final status = visit.finalized ? '已形成足迹' : '进行中';
    return Semantics(
      label: '第 ${index + 1} 个地点，$time，${visit.placeName}，$status',
      // Keep the spoken summary deterministic: child text is already encoded
      // in the explicit label and must not be merged a second time.
      excludeSemantics: true,
      child: Container(
        key: ValueKey('today-footprint-compact-${visit.id}'),
        constraints: const BoxConstraints(minHeight: 44),
        padding: const EdgeInsets.symmetric(
          horizontal: JiYiSpacing.sm,
          vertical: JiYiSpacing.xs,
        ),
        decoration: BoxDecoration(
          color: theme.colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(JiYiRadius.pill),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            DecoratedBox(
              decoration: BoxDecoration(
                color: visit.finalized
                    ? theme.colorScheme.primary
                    : theme.colorScheme.tertiary,
                shape: BoxShape.circle,
              ),
              child: SizedBox.square(
                dimension: 24,
                child: Center(
                  child: Text(
                    '${index + 1}',
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: theme.colorScheme.onPrimary,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(width: JiYiSpacing.xs),
            Text(
              '$time · ${visit.placeName}',
              style: theme.textTheme.labelLarge?.copyWith(
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class FootprintVisitRow extends StatelessWidget {
  const FootprintVisitRow({
    super.key,
    required this.visit,
    required this.elderMode,
  });

  final FootprintVisit visit;
  final bool elderMode;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final status = visit.finalized ? '已形成足迹' : '进行中';
    final range = visit.leftAtLocal == null
        ? '${_clock(visit.arrivedAtLocal)} 起'
        : '${_clock(visit.arrivedAtLocal)} - ${_clock(visit.leftAtLocal!)}';

    return Padding(
      key: ValueKey('today-footprint-visit-${visit.id}'),
      padding: EdgeInsets.symmetric(
        vertical: elderMode ? JiYiSpacing.md : JiYiSpacing.xs,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: JiYiSpacing.xxs),
            child: Icon(
              elderMode
                  ? Icons.place_outlined
                  : (visit.finalized
                      ? Icons.location_on_outlined
                      : Icons.my_location_outlined),
              color: visit.finalized
                  ? theme.colorScheme.primary
                  : theme.colorScheme.tertiary,
            ),
          ),
          const SizedBox(width: JiYiSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  visit.placeName,
                  style: (elderMode
                          ? theme.textTheme.headlineSmall
                          : theme.textTheme.titleMedium)
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: JiYiSpacing.xxs),
                Text(
                  range,
                  style: elderMode
                      ? theme.textTheme.titleMedium
                      : theme.textTheme.bodyMedium,
                ),
                if (!elderMode) ...[
                  const SizedBox(height: JiYiSpacing.xxs),
                  Text(
                    status,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

String _clock(String serverLocalIso) {
  // local timestamp 已由服务端按账号 IANA timezone 计算；这里只取 wall-clock HH:mm，
  // 不调用 DateTime.toLocal()，避免设备时区再次改写服务端已经确定的“今天”语义。
  final match = RegExp(r'T(\d{2}):(\d{2})').firstMatch(serverLocalIso);
  if (match == null) {
    throw const FormatException('invalid server-local datetime');
  }
  return '${match.group(1)}:${match.group(2)}';
}
