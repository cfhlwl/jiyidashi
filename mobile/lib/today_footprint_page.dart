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
    final accepted = await requestAmapPrivacyConsent(
      context,
      _amapPrivacyConsent,
    );
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
    final date = _todayHeroSubtitle(_data);
    return _TodayPageShell(
      hero: JiYiHeroHeader(
        fullBleed: true,
        height: JiYiTodayGeometry.heroHeight,
        atmospheric: true,
        heroAsset: TodayHeroBackground.defaultAsset,
        title: elderMode ? '今天去了哪里' : '今天',
        subtitle: '$date\n${elderMode ? '这里只显示已经形成的足迹。' : '把今天留在这里'}',
      ),
      child: _buildContent(elderMode),
    );
  }

  Widget _buildContent(bool elderMode) {
    if (_loading && _data == null) {
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

    if (_error != null && _data == null) {
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

class _TodayPageShell extends StatelessWidget {
  const _TodayPageShell({required this.hero, required this.child});

  final Widget hero;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: JiYiTodayVisuals.background,
      child: CustomScrollView(
        key: const ValueKey('today-visual-scroll'),
        slivers: [
          SliverToBoxAdapter(
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                Positioned(
                  top: 0,
                  left: 0,
                  right: 0,
                  height: JiYiTodayGeometry.heroHeight,
                  child: hero,
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(
                    JiYiTodayGeometry.pageHorizontalPadding,
                    JiYiTodayGeometry.heroHeight -
                        JiYiTodayGeometry.heroFootprintOverlap,
                    JiYiTodayGeometry.pageHorizontalPadding,
                    JiYiSpacing.xxl,
                  ),
                  child: child,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _TodaySurfaceCard extends StatelessWidget {
  const _TodaySurfaceCard({
    super.key,
    required this.child,
    required this.title,
    this.leading,
    this.trailing,
    this.fixedHeight,
    this.dense = false,
  });

  final Widget child;
  final String title;
  final Widget? leading;
  final Widget? trailing;
  final double? fixedHeight;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final compact = fixedHeight != null && fixedHeight! <= 100;
    final content = Padding(
      padding: compact
          ? const EdgeInsets.fromLTRB(10, 6, 10, 6)
          : dense
          ? const EdgeInsets.fromLTRB(16, 6, 16, 9)
          : const EdgeInsets.fromLTRB(16, 14, 16, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              if (leading != null) ...[
                IconTheme.merge(
                  data: const IconThemeData(
                    size: 28,
                    color: JiYiTodayVisuals.primaryBlue,
                  ),
                  child: leading!,
                ),
                const SizedBox(width: 10),
              ],
              Expanded(
                child: Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleLarge?.copyWith(
                    color: theme.colorScheme.onSurface,
                    fontWeight: FontWeight.w800,
                    height: 1.15,
                  ),
                ),
              ),
              if (trailing != null)
                IconTheme.merge(
                  data: const IconThemeData(
                    size: 28,
                    color: JiYiTodayVisuals.secondaryText,
                  ),
                  child: trailing!,
                ),
            ],
          ),
          SizedBox(
            height: compact
                ? 4
                : dense
                ? 2
                : 8,
          ),
          if (fixedHeight == null) child else Expanded(child: child),
        ],
      ),
    );
    return Material(
      color: JiYiTodayVisuals.card,
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      borderRadius: BorderRadius.circular(JiYiRadius.large),
      clipBehavior: Clip.antiAlias,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: JiYiTodayVisuals.card,
          borderRadius: BorderRadius.circular(JiYiRadius.large),
          boxShadow: const [
            BoxShadow(
              color: JiYiTodayVisuals.cardShadow,
              blurRadius: 14,
              offset: Offset(0, 4),
            ),
          ],
        ),
        child: fixedHeight == null
            ? content
            : SizedBox(height: fixedHeight, child: content),
      ),
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
        const SizedBox(height: JiYiTodayGeometry.sectionGap),
        _memorySection(context),
        const SizedBox(height: JiYiTodayGeometry.sectionGap),
        _quickCapture(context),
        const SizedBox(height: JiYiSpacing.xl),
        const JiYiSectionHeader(title: '家庭共享', subtitle: '只有家人明确授权给你的内容才会被读取。'),
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
      return _TodaySurfaceCard(
        key: const ValueKey('today-footprint-empty'),
        leading: Icon(Icons.route_outlined, color: theme.colorScheme.primary),
        title: elderMode ? '今天去了哪里' : '今日足迹',
        trailing: const Icon(Icons.chevron_right),
        child: JiYiEmptyState(
          icon: Icons.location_off_outlined,
          title: elderMode ? '今天还没有形成足迹' : '今天还没有形成足迹',
          message: elderMode ? '不会用当前位置猜测你去过哪里。' : '形成到访后，会在这里按时间留下今天的足迹。',
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
      child: _TodaySurfaceCard(
        key: const ValueKey('today-footprint-loaded'),
        leading: Icon(
          Icons.location_on_outlined,
          color: theme.colorScheme.primary,
        ),
        title: elderMode ? '今天去了哪里' : '今日足迹',
        trailing: const Icon(Icons.chevron_right),
        fixedHeight: JiYiTodayGeometry.footprintCardHeight,
        dense: true,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              '${footprint.visits.length} 个地点片段',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.titleMedium?.copyWith(
                color: JiYiTodayVisuals.navy,
                fontWeight: FontWeight.w700,
                height: 1.1,
              ),
            ),
            Text(
              '按今天真实形成的到访记录整理',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.bodySmall?.copyWith(
                color: JiYiTodayVisuals.secondaryText,
                height: 1.15,
              ),
            ),
            const SizedBox(height: 0),
            Expanded(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(JiYiRadius.control),
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    IgnorePointer(
                      child: JiYiFootprintMap(
                        visits: footprint.visits,
                        privacyAccepted: mapPrivacyAccepted,
                        selectedIndex: 0,
                        onSelected: (_) {},
                        interactive: false,
                        height: JiYiTodayGeometry.mapViewportHeight,
                      ),
                    ),
                    for (
                      var index = 0;
                      index < footprint.visits.length && index < 2;
                      index++
                    )
                      Positioned(
                        top: 10,
                        left: index == 0 ? 10 : null,
                        right: index == 1 ? 10 : null,
                        child: _TodayVisitPill(
                          index: index,
                          visit: footprint.visits[index],
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _memorySection(BuildContext context) {
    if (memoryUnavailable) {
      return const _TodaySurfaceCard(
        title: '今日记忆',
        leading: Icon(Icons.photo_library_outlined),
        trailing: Icon(Icons.chevron_right),
        child: JiYiStatusBanner(
          kind: JiYiStatusKind.warning,
          title: '今日记忆暂时没有整理好',
          message: '足迹仍可正常查看，稍后回来会重新读取今天的记忆。',
        ),
      );
    }
    if (memories.isEmpty) {
      return const _TodaySurfaceCard(
        title: '今日记忆',
        leading: Icon(Icons.photo_library_outlined),
        trailing: Icon(Icons.chevron_right),
        child: JiYiEmptyState(
          icon: Icons.auto_stories_outlined,
          title: '今天还没有主动记录',
          message: '记下一句话、一张照片或一段语音后，会从这里开始积累。',
        ),
      );
    }
    return _TodaySurfaceCard(
      title: '今日记忆',
      leading: const Icon(Icons.photo_library_outlined),
      trailing: const Icon(Icons.chevron_right),
      fixedHeight: JiYiTodayGeometry.memorySectionHeight,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final width = (constraints.maxWidth - 8) / 2;
          return Wrap(
            spacing: 8,
            runSpacing: 10,
            children: [
              for (final item in memories.take(4))
                SizedBox(
                  width: width,
                  child: _TodayMemoryCard(
                    api: api,
                    item: item,
                    mediaCache: mediaCache,
                    photoThumbnailBuilder: photoThumbnailBuilder,
                    onTap: () {
                      Navigator.of(context).push<bool>(
                        MaterialPageRoute<bool>(
                          builder: (_) => MemoryDetailPage(
                            api: api,
                            memoryId: item.id,
                            mediaCache: mediaCache,
                            amapPrivacyConsent: amapPrivacyConsent,
                          ),
                        ),
                      );
                    },
                  ),
                ),
            ],
          );
        },
      ),
    );
  }

  Widget _quickCapture(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final actions = [
          (Icons.mic_none_outlined, '说一段'),
          (Icons.edit_note_outlined, '写下来'),
          (Icons.photo_camera_outlined, '拍张照'),
        ];
        return _TodaySurfaceCard(
          title: '记一下',
          leading: const Icon(
            Icons.edit_outlined,
            color: JiYiTodayVisuals.primaryBlue,
          ),
          fixedHeight: JiYiTodayGeometry.quickCaptureHeight,
          child: Row(
            children: [
              for (var index = 0; index < actions.length; index++) ...[
                if (index > 0) const SizedBox(width: 8),
                Expanded(
                  child: _TodayQuickAction(
                    icon: actions[index].$1,
                    title: actions[index].$2,
                    onTap: onCapture,
                    accent: index == 0
                        ? JiYiTodayVisuals.primaryBlue
                        : index == 1
                        ? JiYiTodayVisuals.captureOrange
                        : JiYiTodayVisuals.captureGreen,
                  ),
                ),
              ],
            ],
          ),
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
    this.mediaCache,
    this.photoThumbnailBuilder,
  });

  final JiYiApiClient api;
  final TimelineReadItem item;
  final VoidCallback onTap;
  final LocalMediaCache? mediaCache;
  final LocalMediaThumbnailBuilder? photoThumbnailBuilder;

  Widget _photoThumbnail(BuildContext context) {
    final mediaId = item.mediaId!;
    final builder = photoThumbnailBuilder;
    if (builder != null) {
      return SizedBox(
        key: ValueKey('today-photo-${item.id}'),
        width: double.infinity,
        height: 117,
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
      width: double.infinity,
      height: 117,
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final title = item.title ?? _todayMemoryTypeLabel(item.memoryType);
    return Material(
      color: JiYiTodayVisuals.card,
      borderRadius: BorderRadius.circular(JiYiRadius.card),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (item.memoryType == 'PHOTO' && item.mediaId != null)
              _photoThumbnail(context)
            else
              SizedBox(
                width: double.infinity,
                height: 117,
                child: DecoratedBox(
                  decoration: const BoxDecoration(
                    color: Color(0xFFEAF2F7),
                  ),
                  child: Center(
                    child: Icon(
                      _todayMemoryIcon(item.memoryType),
                      size: JiYiIconSize.large,
                      color: theme.colorScheme.primary,
                    ),
                  ),
                ),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(9, 8, 9, 7),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.titleSmall?.copyWith(
                      color: JiYiTodayVisuals.navy,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  if (item.content != null && item.content!.trim().isNotEmpty)
                    Text(
                      item.content!,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: JiYiTodayVisuals.secondaryText,
                        height: 1.35,
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

class _TodayQuickAction extends StatelessWidget {
  const _TodayQuickAction({
    required this.icon,
    required this.title,
    required this.onTap,
    required this.accent,
  });

  final IconData icon;
  final String title;
  final VoidCallback? onTap;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: accent.withValues(alpha: 0.10),
      borderRadius: BorderRadius.circular(JiYiRadius.card),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        child: SizedBox(
          height: 44,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: JiYiIconSize.medium, color: accent),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall?.copyWith(
                    color: accent,
                    fontWeight: FontWeight.w700,
                    height: 1.05,
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
    final parsed = DateTime.tryParse('${day}T00:00:00');
    if (parsed != null) {
      const weekdays = <String>['一', '二', '三', '四', '五', '六', '日'];
      return '${parsed.month}月${parsed.day}日 · 星期${weekdays[parsed.weekday - 1]}';
    }
  }
  return '正在整理今天';
}

class _TodayVisitPill extends StatelessWidget {
  const _TodayVisitPill({required this.index, required this.visit});

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
            Icon(
              _todayVisitIcon(visit),
              size: 18,
              color: visit.finalized
                  ? JiYiTodayVisuals.primaryBlue
                  : JiYiTodayVisuals.mapGreen,
            ),
            const SizedBox(width: 4),
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

IconData _todayVisitIcon(FootprintVisit visit) {
  final category = visit.category?.toUpperCase();
  if (category == 'HOME' || visit.placeName.contains('家')) {
    return Icons.home_outlined;
  }
  if (category == 'PARK' || visit.placeName.contains('公园')) {
    return Icons.forest_outlined;
  }
  return Icons.location_on_outlined;
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
                  style:
                      (elderMode
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
