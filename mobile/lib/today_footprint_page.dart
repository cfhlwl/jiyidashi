import 'package:flutter/material.dart';

import 'api_client.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';

class TodayPage extends StatefulWidget {
  const TodayPage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<TodayPage> createState() => _TodayPageState();
}

class _TodayPageState extends State<TodayPage> {
  late Future<Map<String, dynamic>> _future = widget.api.getTodayFootprint();

  void _reload() {
    setState(() {
      _future = widget.api.getTodayFootprint();
    });
  }

  @override
  Widget build(BuildContext context) {
    return JiYiPageFrame(
      title: '今天',
      subtitle: '按账号时区回看今天真实形成的地点足迹。',
      child: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
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

          if (snapshot.hasError) {
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
                  onPressed: _reload,
                  icon: const Icon(Icons.refresh),
                  label: const Text('重新加载'),
                ),
              ],
            );
          }

          late final _TodayFootprint footprint;
          try {
            footprint = _TodayFootprint.fromJson(snapshot.data!);
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
                  onPressed: _reload,
                  icon: const Icon(Icons.refresh),
                  label: const Text('重新加载'),
                ),
              ],
            );
          }

          return _TodayFootprintBody(footprint: footprint);
        },
      ),
    );
  }
}

class _TodayFootprintBody extends StatelessWidget {
  const _TodayFootprintBody({required this.footprint});

  final _TodayFootprint footprint;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (footprint.visits.isEmpty) {
      return JiYiSectionCard(
        key: const ValueKey('today-footprint-empty'),
        leading: Icon(Icons.route_outlined, color: theme.colorScheme.primary),
        title: '今日足迹',
        subtitle: '${footprint.day} · ${footprint.timezone}',
        child: const JiYiEmptyState(
          icon: Icons.location_off_outlined,
          title: '今天还没有形成足迹',
          message: '这里只有服务端已经派生出的 Visit；不会用手机当前位置或猜测内容补一条记录。',
        ),
      );
    }

    return JiYiSectionCard(
      key: const ValueKey('today-footprint-loaded'),
      leading: Icon(Icons.route_outlined, color: theme.colorScheme.primary),
      title: '今日足迹',
      subtitle:
          '${footprint.day} · ${footprint.timezone} · ${footprint.visits.length} 条地点记录',
      child: Column(
        children: [
          for (var index = 0; index < footprint.visits.length; index++) ...[
            _FootprintVisitRow(visit: footprint.visits[index]),
            if (index != footprint.visits.length - 1)
              const Divider(height: JiYiSpacing.lg),
          ],
        ],
      ),
    );
  }
}

class _FootprintVisitRow extends StatelessWidget {
  const _FootprintVisitRow({required this.visit});

  final _FootprintVisit visit;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final status = visit.finalized ? '已形成足迹' : '进行中';
    final range = visit.leftAtLocal == null
        ? '${_clock(visit.arrivedAtLocal)} 起'
        : '${_clock(visit.arrivedAtLocal)} - ${_clock(visit.leftAtLocal!)}';

    return Padding(
      key: ValueKey('today-footprint-visit-${visit.id}'),
      padding: const EdgeInsets.symmetric(vertical: JiYiSpacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: JiYiSpacing.xxs),
            child: Icon(
              visit.finalized
                  ? Icons.location_on_outlined
                  : Icons.my_location_outlined,
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
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.xxs),
                Text(range, style: theme.textTheme.bodyMedium),
                const SizedBox(height: JiYiSpacing.xxs),
                Text(
                  '$status · ${visit.visitSource}',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

String _clock(String serverLocalIso) {
  // [人工注释][S2-012] local timestamp 已由服务端按账号 IANA timezone 计算；
  // 这里只取 wall-clock HH:mm，不调用 DateTime.toLocal()，避免设备时区再次改写。
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
        day.trim().isEmpty ||
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
    DateTime.parse(arrivedAtLocal);
    if (leftAtLocal is String) DateTime.parse(leftAtLocal);
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
