import 'package:flutter/material.dart';

import 'api_client.dart';
import 'memory_detail_page.dart';
import 'timeline_models.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_format.dart';
import 'ui/jiyi_tokens.dart';
import 'v2/family_api.dart';

// Today Footprint 是服务端按账号时区和 Visit overlap 生成的权威只读投影。
// Flutter 只做严格协议解析与展示；网络/协议失败时 fail closed，不用设备当前位置或客户端猜测补足“今天”。
class TodayPage extends StatefulWidget {
  const TodayPage({
    super.key,
    required this.api,
    this.elderMode = false,
    this.onCapture,
    this.onOpenFamily,
  });

  final JiYiApiClient api;
  final bool elderMode;
  final VoidCallback? onCapture;
  final VoidCallback? onOpenFamily;

  @override
  State<TodayPage> createState() => _TodayPageState();
}

class _TodayPageState extends State<TodayPage> {
  Map<String, dynamic>? _data;
  List<TimelineReadItem> _todayMemories = const [];
  bool _memoryUnavailable = false;
  int? _familyMemberCount;
  Object? _error;
  bool _loading = true;
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    _load();
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
        _familyMemberCount = null;
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

      // Validate the Today authority before using its account-timezone day as the
      // boundary for the secondary memory projection.
      final footprint = _TodayFootprint.fromJson(data);
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

      int? familyMemberCount;
      try {
        final family = await FamilyApi(widget.api).getFamily();
        if (!current()) return;
        familyMemberCount = family.members.length;
      } catch (_) {
        if (!current()) return;
      }

      setState(() {
        _data = data;
        _todayMemories = memories;
        _memoryUnavailable = memoryUnavailable;
        _familyMemberCount = familyMemberCount;
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
      hero: JiYiHeroHeader(
        eyebrow: '迹忆 · 今天',
        title: elderMode ? '今天去了哪里' : '今天好',
        subtitle: _todayHeroSubtitle(_data),
        icon: Icons.wb_sunny_outlined,
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

    late final _TodayFootprint footprint;
    try {
      footprint = _TodayFootprint.fromJson(_data!);
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
      familyMemberCount: _familyMemberCount,
      elderMode: elderMode,
      onCapture: widget.onCapture,
      onOpenFamily: widget.onOpenFamily,
    );
  }
}

class _TodayExperienceBody extends StatelessWidget {
  const _TodayExperienceBody({
    required this.api,
    required this.footprint,
    required this.memories,
    required this.memoryUnavailable,
    required this.familyMemberCount,
    required this.elderMode,
    this.onCapture,
    this.onOpenFamily,
  });

  final JiYiApiClient api;
  final _TodayFootprint footprint;
  final List<TimelineReadItem> memories;
  final bool memoryUnavailable;
  final int? familyMemberCount;
  final bool elderMode;
  final VoidCallback? onCapture;
  final VoidCallback? onOpenFamily;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        JiYiSectionHeader(
          title: elderMode ? '今天去了哪里' : '今日足迹',
          subtitle: elderMode
              ? '只显示已经形成的足迹。'
              : jiyiDisplayDate(footprint.day),
        ),
        const SizedBox(height: JiYiSpacing.sm),
        _footprintCard(theme),
        const SizedBox(height: JiYiSpacing.xl),
        const JiYiSectionHeader(
          title: '今日记忆',
          subtitle: '今天主动记下的内容，会在这里留下可以回看的片段。',
        ),
        const SizedBox(height: JiYiSpacing.sm),
        _memorySection(context),
        const SizedBox(height: JiYiSpacing.xl),
        const JiYiSectionHeader(
          title: '快速记录',
          subtitle: '现在想记住的事，不必等到以后。',
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
          leading: const Icon(
            Icons.family_restroom_outlined,
            color: JiYiProductColors.family,
          ),
          title: familyMemberCount == null
              ? '家庭内容按授权显示'
              : '家庭 · $familyMemberCount 位成员',
          subtitle: familyMemberCount == null
              ? '进入家庭查看成员和共享权限。'
              : '进入家庭查看已经明确授权给你的内容。',
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

  Widget _footprintCard(ThemeData theme) {
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

    return JiYiSectionCard(
      key: const ValueKey('today-footprint-loaded'),
      leading: Icon(Icons.route_outlined, color: theme.colorScheme.primary),
      title: '${footprint.visits.length} 个地点片段',
      subtitle: '按今天真实形成的到访记录整理',
      child: Column(
        children: [
          for (var index = 0; index < footprint.visits.length; index++) ...[
            _FootprintVisitRow(
              visit: footprint.visits[index],
              elderMode: elderMode,
            ),
            if (index != footprint.visits.length - 1)
              const Divider(height: JiYiSpacing.lg),
          ],
        ],
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
    return Column(
      children: [
        for (var index = 0; index < memories.length; index++) ...[
          _TodayMemoryCard(
            item: memories[index],
            onTap: () {
              Navigator.of(context).push<bool>(
                MaterialPageRoute<bool>(
                  builder: (_) => MemoryDetailPage(
                    api: api,
                    memoryId: memories[index].id,
                  ),
                ),
              );
            },
          ),
          if (index != memories.length - 1)
            const SizedBox(height: JiYiSpacing.sm),
        ],
      ],
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
  const _TodayMemoryCard({required this.item, required this.onTap});

  final TimelineReadItem item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final title = item.title ?? _todayMemoryTypeLabel(item.memoryType);
    return Material(
      color: JiYiProductColors.surface,
      borderRadius: BorderRadius.circular(JiYiRadius.card),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        child: Padding(
          padding: const EdgeInsets.all(JiYiSpacing.md),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              DecoratedBox(
                decoration: BoxDecoration(
                  color: JiYiProductColors.surfaceSoft,
                  borderRadius: BorderRadius.circular(JiYiRadius.control),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(JiYiSpacing.sm),
                  child: Icon(
                    _todayMemoryIcon(item.memoryType),
                    color: JiYiProductColors.brandPrimary,
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
                          color: JiYiProductColors.textSecondary,
                        ),
                      ),
                    ],
                    const SizedBox(height: JiYiSpacing.xs),
                    Text(
                      jiyiDisplayTime(item.occurredAt),
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: JiYiProductColors.textTertiary,
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
      color: JiYiProductColors.surface,
      borderRadius: BorderRadius.circular(JiYiRadius.card),
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
                Icon(icon, color: JiYiProductColors.brandPrimary),
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
                    color: JiYiProductColors.textSecondary,
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
  if (day is String && _isStrictDateOnly(day)) {
    return jiyiDisplayDate(day);
  }
  return '正在整理今天';
}

class _FootprintVisitRow extends StatelessWidget {
  const _FootprintVisitRow({
    required this.visit,
    required this.elderMode,
  });

  final _FootprintVisit visit;
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

class _TodayFootprint {
  const _TodayFootprint({
    required this.timezone,
    required this.day,
    required this.visits,
  });

  final String timezone;
  final String day;
  final List<_FootprintVisit> visits;

  factory _TodayFootprint.fromJson(Map<String, dynamic> data) {
    final timezone = data['timezone'];
    final day = data['day'];
    final visits = data['visits'];
    if (timezone is! String ||
        timezone.trim().isEmpty ||
        day is! String ||
        !_isStrictDateOnly(day) ||
        visits is! List<dynamic>) {
      throw const FormatException('invalid today footprint');
    }
    return _TodayFootprint(
      timezone: timezone,
      day: day,
      visits: visits
          .map((item) {
            if (item is! Map<String, dynamic>) {
              throw const FormatException('invalid footprint visit');
            }
            return _FootprintVisit.fromJson(item);
          })
          .toList(growable: false),
    );
  }
}

class _FootprintVisit {
  const _FootprintVisit({
    required this.id,
    required this.placeId,
    required this.placeName,
    required this.arrivedAt,
    required this.leftAt,
    required this.arrivedAtLocal,
    required this.leftAtLocal,
    required this.confidence,
    required this.visitSource,
    required this.finalized,
  });

  final String id;
  final String placeId;
  final String placeName;
  final String arrivedAt;
  final String? leftAt;
  final String arrivedAtLocal;
  final String? leftAtLocal;
  final double confidence;
  final String visitSource;
  final bool finalized;

  factory _FootprintVisit.fromJson(Map<String, dynamic> data) {
    final id = data['id'];
    final placeId = data['place_id'];
    final placeName = data['place_name'];
    final arrivedAt = data['arrived_at'];
    final leftAt = data['left_at'];
    final arrivedAtLocal = data['arrived_at_local'];
    final leftAtLocal = data['left_at_local'];
    final confidence = data['confidence'];
    final visitSource = data['visit_source'];
    final finalized = data['visit_finalized'];
    if (id is! String ||
        id.trim().isEmpty ||
        placeId is! String ||
        placeId.trim().isEmpty ||
        placeName is! String ||
        placeName.trim().isEmpty ||
        arrivedAt is! String ||
        arrivedAt.trim().isEmpty ||
        (leftAt != null && leftAt is! String) ||
        arrivedAtLocal is! String ||
        arrivedAtLocal.trim().isEmpty ||
        (leftAtLocal != null && leftAtLocal is! String) ||
        confidence is! num ||
        !confidence.isFinite ||
        visitSource is! String ||
        visitSource.trim().isEmpty ||
        finalized is! bool) {
      throw const FormatException('invalid footprint visit');
    }
    if (!_isStrictIsoDateTime(arrivedAt) ||
        (leftAt is String && !_isStrictIsoDateTime(leftAt)) ||
        !_isStrictIsoDateTime(arrivedAtLocal) ||
        (leftAtLocal is String && !_isStrictIsoDateTime(leftAtLocal))) {
      throw const FormatException('invalid footprint visit');
    }
    return _FootprintVisit(
      id: id,
      placeId: placeId,
      placeName: placeName,
      arrivedAt: arrivedAt,
      leftAt: leftAt as String?,
      arrivedAtLocal: arrivedAtLocal,
      leftAtLocal: leftAtLocal as String?,
      confidence: confidence.toDouble(),
      visitSource: visitSource,
      finalized: finalized,
    );
  }
}


bool _isStrictDateOnly(String value) {
  final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch(value);
  if (match == null) return false;
  final year = int.parse(match.group(1)!);
  final month = int.parse(match.group(2)!);
  final day = int.parse(match.group(3)!);
  final parsed = DateTime.utc(year, month, day);
  return parsed.year == year && parsed.month == month && parsed.day == day;
}

bool _isStrictIsoDateTime(String value) {
  final match = RegExp(
    r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$',
  ).firstMatch(value);
  if (match == null || !_isStrictDateOnly(value.substring(0, 10))) return false;
  final hour = int.parse(match.group(4)!);
  final minute = int.parse(match.group(5)!);
  final second = int.parse(match.group(6)!);
  if (hour > 23 || minute > 59 || second > 59) return false;
  return DateTime.tryParse(value) != null;
}
