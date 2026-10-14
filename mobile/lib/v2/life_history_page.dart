// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_format.dart';
import '../ui/jiyi_timezone.dart';
import '../ui/jiyi_tokens.dart';
import '../ui/jiyi_v3_components.dart';
import 'life_event_detail_page.dart';
import 'life_models.dart';
import 'life_stage_detail_page.dart';
import 'v2_api.dart';
import 'v2_authority.dart';

/// Server-authoritative cross-year history. This page owns presentation and
/// pagination only; event/stage truth remains in V2Api and strict V2 models.
class LifeHistoryPage extends StatefulWidget {
  const LifeHistoryPage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<LifeHistoryPage> createState() => _LifeHistoryPageState();
}

class _LifeHistoryPageState extends State<LifeHistoryPage> {
  late V2Api v2;
  final V2Authority authority = V2Authority();
  late final TextEditingController startYear;
  late final TextEditingController endYear;

  JiYiApiClient? _boundApi;
  String? _boundOwner;
  int? _boundSessionVersion;
  bool _rebindScheduled = false;
  V2LifeHistoryPage? page;
  List<V2LifeHistoryItem> items = const [];
  String? cursor;
  bool loading = false;
  String? error;

  bool get _bindingMatches =>
      identical(_boundApi, widget.api) &&
      _boundOwner == widget.api.authenticatedUserId &&
      _boundSessionVersion == widget.api.sessionVersion;

  @override
  void initState() {
    super.initState();
    v2 = V2Api(widget.api);
    _rememberBinding();
    final year = DateTime.now().year;
    startYear = TextEditingController(text: (year - 5).toString());
    endYear = TextEditingController(text: year.toString());
    startYear.addListener(_rangeChanged);
    endYear.addListener(_rangeChanged);
  }

  void _rememberBinding() {
    _boundApi = widget.api;
    _boundOwner = widget.api.authenticatedUserId;
    _boundSessionVersion = widget.api.sessionVersion;
  }

  @override
  void didUpdateWidget(covariant LifeHistoryPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.api, widget.api)) _scheduleRebind();
  }

  void _scheduleRebind() {
    if (_rebindScheduled) return;
    _rebindScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _rebindScheduled = false;
      if (mounted) _rebind();
    });
  }

  void _rebind() {
    authority.invalidate();
    v2 = V2Api(widget.api);
    _rememberBinding();
    if (!mounted) return;
    setState(() {
      page = null;
      items = const [];
      cursor = null;
      loading = false;
      error = null;
    });
  }

  void _checkBinding() {
    if (!_bindingMatches) _scheduleRebind();
  }

  @override
  void dispose() {
    startYear.removeListener(_rangeChanged);
    endYear.removeListener(_rangeChanged);
    startYear.dispose();
    endYear.dispose();
    authority.invalidate();
    super.dispose();
  }

  void _rangeChanged() {
    authority.invalidate();
    if (!mounted) return;
    setState(() {
      page = null;
      items = const [];
      cursor = null;
      error = null;
      loading = false;
    });
  }

  ({int start, int end})? _range() {
    final start = int.tryParse(startYear.text.trim());
    final end = int.tryParse(endYear.text.trim());
    if (start == null || end == null || start < 1 || end > 9998 || start > end) {
      return null;
    }
    return (start: start, end: end);
  }

  String _itemKey(V2LifeHistoryItem item) {
    final id = item.lifeEventId ?? item.lifeStageId;
    return '${item.kind}:${id ?? item.title}:${item.occurredAt}';
  }

  Future<void> _load({required bool append}) async {
    if (loading) return;
    final range = _range();
    if (range == null) {
      setState(() => error = '请输入有效的年份范围（1–9998，开始年份不晚于结束年份）。');
      return;
    }
    final nextCursor = append ? cursor : null;
    if (append && nextCursor == null) return;
    final identity = 'history:${range.start}:${range.end}:${nextCursor ?? 'root'}';
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = authority.capture(widget.api, identity);
    } catch (exc) {
      if (mounted) setState(() => error = exc.toString());
      return;
    }
    setState(() {
      loading = true;
      error = null;
      if (!append) {
        page = null;
        items = const [];
        cursor = null;
      }
    });
    try {
      final result = await v2.getLifeHistory(
        startYear: range.start,
        endYear: range.end,
        limit: 50,
        cursor: nextCursor,
      );
      if (!mounted ||
          !_bindingMatches ||
          !authority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      final merged = <String, V2LifeHistoryItem>{
        for (final item in append ? items : const <V2LifeHistoryItem>[]) _itemKey(item): item,
      };
      for (final item in result.items) merged[_itemKey(item)] = item;
      setState(() {
        page = result;
        items = List.unmodifiable(merged.values);
        cursor = result.nextCursor;
        loading = false;
      });
    } catch (exc) {
      if (!mounted ||
          !_bindingMatches ||
          !authority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      setState(() {
        error = exc.toString();
        loading = false;
      });
    }
  }

  Future<void> _openItem(V2LifeHistoryItem item) async {
    if (!_bindingMatches || loading) return;
    final id = item.lifeEventId ?? item.lifeStageId;
    if (id == null) return;
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = authority.capture(widget.api, 'history-detail:$id');
    } catch (_) {
      return;
    }
    final detail = item.kind == 'LIFE_EVENT'
        ? LifeEventDetailPage(api: widget.api, eventId: id)
        : LifeStageDetailPage(api: widget.api, stageId: id);
    if (!mounted || !authority.isCurrent(widget.api, snapshot, snapshot.identity)) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(builder: (_) => detail),
    );
  }

  V3StateSurfaceVariant _errorVariant() {
    final value = error ?? '';
    if (value.contains('网络') || value.contains('连接') || value.contains('Transport')) {
      return V3StateSurfaceVariant.offline;
    }
    if (value.contains('401') || value.contains('403') || value.contains('权限')) {
      return V3StateSurfaceVariant.blocked;
    }
    return V3StateSurfaceVariant.error;
  }

  @override
  Widget build(BuildContext context) {
    _checkBinding();
    final currentPage = page;
    final timezone = currentPage?.timezone ?? 'UTC';
    return V3PageScaffold(
      topBar: V3TopBar(
        title: '多年时间线',
        subtitle: '按服务端时区回看真实记录',
        onBack: () => Navigator.of(context).maybePop(),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          V3SurfaceCard(
            key: const ValueKey('life-history-range-card'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const V3SectionHeader(
                  title: '回看这些年',
                  subtitle: '只显示服务端返回的经历、阶段和关联地点。',
                ),
                const SizedBox(height: JiYiSpacing.md),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final fields = [
                      Expanded(
                        child: TextField(
                          controller: startYear,
                          keyboardType: TextInputType.number,
                          decoration: const InputDecoration(labelText: '开始年份'),
                        ),
                      ),
                      const SizedBox(width: JiYiSpacing.sm),
                      Expanded(
                        child: TextField(
                          controller: endYear,
                          keyboardType: TextInputType.number,
                          decoration: const InputDecoration(labelText: '结束年份'),
                        ),
                      ),
                    ];
                    return constraints.maxWidth < 360
                        ? Column(children: [fields[0], fields[2]])
                        : Row(children: fields);
                  },
                ),
                const SizedBox(height: JiYiSpacing.md),
                FilledButton.icon(
                  key: const ValueKey('life-history-submit'),
                  onPressed: loading ? null : () => _load(append: false),
                  icon: const Icon(Icons.timeline_outlined),
                  label: Text(loading && items.isEmpty ? '正在读取…' : '查看时间线'),
                ),
              ],
            ),
          ),
          if (error != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            V3StateSurface(
              variant: _errorVariant(),
              title: _errorVariant() == V3StateSurfaceVariant.offline
                  ? '暂时离线'
                  : '时间线暂时无法显示',
              message: error!,
              primaryAction: V3StateAction(label: '重试', onPressed: () => _load(append: false)),
            ),
          ],
          if (currentPage != null) ...[
            const SizedBox(height: JiYiSpacing.lg),
            V3SectionHeader(
              title: '${currentPage.startYear}–${currentPage.endYear}',
              subtitle: '数据截至 ${jiyiDisplayDate(currentPage.asOf)} · $timezone',
              count: items.length,
            ),
            const SizedBox(height: JiYiSpacing.sm),
            if (items.isEmpty)
              const V3StateSurface(
                variant: V3StateSurfaceVariant.empty,
                title: '这段时间还没有记录',
                message: '没有足够的真实经历或人生阶段可以展示。',
              )
            else
              _TimelineList(items: items, timezone: timezone, onTap: _openItem),
            if (cursor != null) ...[
              const SizedBox(height: JiYiSpacing.md),
              OutlinedButton.icon(
                key: const ValueKey('life-history-load-more'),
                onPressed: loading ? null : () => _load(append: true),
                icon: const Icon(Icons.expand_more),
                label: Text(loading ? '正在读取…' : '加载更多'),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

class _TimelineList extends StatelessWidget {
  const _TimelineList({required this.items, required this.timezone, required this.onTap});

  final List<V2LifeHistoryItem> items;
  final String timezone;
  final Future<void> Function(V2LifeHistoryItem item) onTap;

  DateTime _wallClock(String value) {
    return jiyiDateTimeInTimezone(value, timezone) ??
        DateTime.tryParse(value)?.toUtc() ??
        DateTime.utc(1970);
  }

  String _kindLabel(V2LifeHistoryItem item) {
    if (item.kind == 'LIFE_EVENT') return '人生经历';
    return item.kind == 'LIFE_STAGE_STARTED' ? '阶段开始' : '阶段结束';
  }

  String _dateTimeLabel(V2LifeHistoryItem item) {
    final date = _wallClock(item.occurredAt);
    String two(int value) => value.toString().padLeft(2, '0');
    return '${date.year}年${date.month}月${date.day}日 ${two(date.hour)}:${two(date.minute)}';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    String? lastGroup;
    final children = <Widget>[];
    for (final item in items) {
      final date = _wallClock(item.occurredAt);
      final group = '${date.year}年${date.month}月';
      if (group != lastGroup) {
        children.add(
          Padding(
            key: ValueKey('history-group-$group'),
            padding: const EdgeInsets.only(top: JiYiSpacing.md, bottom: JiYiSpacing.xs),
            child: Text(
              group,
              style: theme.textTheme.titleSmall?.copyWith(
                color: theme.colorScheme.primary,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        );
        lastGroup = group;
      }
      final hasDetail = item.lifeEventId != null || item.lifeStageId != null;
      children.add(
        V3SurfaceCard(
          key: ValueKey('history-item-${item.lifeEventId ?? item.lifeStageId ?? item.occurredAt}'),
          padding: const EdgeInsets.all(JiYiSpacing.md),
          semanticLabel: item.title,
          onTap: hasDetail ? () => onTap(item) : null,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              DecoratedBox(
                decoration: BoxDecoration(
                  color: theme.colorScheme.primaryContainer,
                  shape: BoxShape.circle,
                ),
                child: Padding(
                  padding: const EdgeInsets.all(JiYiSpacing.sm),
                  child: Icon(
                    item.kind == 'LIFE_EVENT' ? Icons.event_note_outlined : Icons.view_timeline_outlined,
                    color: theme.colorScheme.onPrimaryContainer,
                  ),
                ),
              ),
              const SizedBox(width: JiYiSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(item.title, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
                    const SizedBox(height: JiYiSpacing.xxs),
                    Text(
                      '${_kindLabel(item)} · ${_dateTimeLabel(item)}',
                      style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                    if (item.placeId != null) ...[
                      const SizedBox(height: JiYiSpacing.xs),
                      Text('包含已关联地点记录', style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.primary)),
                    ],
                  ],
                ),
              ),
              if (hasDetail) const Icon(Icons.chevron_right),
            ],
          ),
        ),
      );
      children.add(const SizedBox(height: JiYiSpacing.sm));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children);
  }
}
