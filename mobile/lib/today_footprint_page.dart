import 'package:flutter/material.dart';

import 'api_client.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';

// Today Footprint 是服务端按账号时区和 Visit overlap 生成的权威只读投影。
// Flutter 只做严格协议解析与展示；网络/协议失败时 fail closed，不用设备当前位置或客户端猜测补足“今天”。
class TodayPage extends StatefulWidget {
  const TodayPage({
    super.key,
    required this.api,
    this.elderMode = false,
  });

  final JiYiApiClient api;
  final bool elderMode;

  @override
  State<TodayPage> createState() => _TodayPageState();
}

class _TodayPageState extends State<TodayPage> {
  Map<String, dynamic>? _data;
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
      setState(() => _data = data);
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
          : '按账号时区回看今天真实形成的地点足迹。',
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
            message: '当前没有可靠的服务端足迹结果，请检查网络后重试。',
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
            message: '服务端返回的数据不完整，已停止展示，避免把未知信息当成真实足迹。',
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

    return _TodayFootprintBody(
      footprint: footprint,
      elderMode: elderMode,
    );
  }
}

class _TodayFootprintBody extends StatelessWidget {
  const _TodayFootprintBody({
    required this.footprint,
    required this.elderMode,
  });

  final _TodayFootprint footprint;
  final bool elderMode;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (footprint.visits.isEmpty) {
      return JiYiSectionCard(
        key: const ValueKey('today-footprint-empty'),
        leading: Icon(Icons.route_outlined, color: theme.colorScheme.primary),
        title: elderMode ? '今天还没有形成足迹' : '今日足迹',
        subtitle: elderMode ? null : '${footprint.day} · ${footprint.timezone}',
        child: JiYiEmptyState(
          icon: Icons.location_off_outlined,
          title: '今天还没有形成足迹',
          message: elderMode
              ? '这里只显示已经形成的足迹，不会用当前位置猜测。'
              : '这里只有服务端已经派生出的 Visit；不会用手机当前位置或猜测内容补一条记录。',
        ),
      );
    }

    return JiYiSectionCard(
      key: const ValueKey('today-footprint-loaded'),
      leading: Icon(Icons.route_outlined, color: theme.colorScheme.primary),
      title: elderMode ? '今天去了哪里' : '今日足迹',
      subtitle: elderMode
          ? null
          : '${footprint.day} · ${footprint.timezone} · ${footprint.visits.length} 条地点记录',
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
                    '$status · ${visit.visitSource}',
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
    required this.placeName,
    required this.arrivedAtLocal,
    required this.leftAtLocal,
    required this.visitSource,
    required this.finalized,
  });

  final String id;
  final String placeName;
  final String arrivedAtLocal;
  final String? leftAtLocal;
  final String visitSource;
  final bool finalized;

  factory _FootprintVisit.fromJson(Map<String, dynamic> data) {
    final id = data['id'];
    final placeName = data['place_name'];
    final arrivedAtLocal = data['arrived_at_local'];
    final leftAtLocal = data['left_at_local'];
    final visitSource = data['visit_source'];
    final finalized = data['visit_finalized'];
    if (id is! String ||
        id.trim().isEmpty ||
        placeName is! String ||
        placeName.trim().isEmpty ||
        arrivedAtLocal is! String ||
        arrivedAtLocal.trim().isEmpty ||
        (leftAtLocal != null && leftAtLocal is! String) ||
        visitSource is! String ||
        visitSource.trim().isEmpty ||
        finalized is! bool) {
      throw const FormatException('invalid footprint visit');
    }
    if (!_isStrictIsoDateTime(arrivedAtLocal)) {
      throw const FormatException('invalid footprint visit');
    }
    if (leftAtLocal is String && !_isStrictIsoDateTime(leftAtLocal)) {
      throw const FormatException('invalid footprint visit');
    }
    return _FootprintVisit(
      id: id,
      placeName: placeName,
      arrivedAtLocal: arrivedAtLocal,
      leftAtLocal: leftAtLocal as String?,
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
