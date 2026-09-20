import 'package:flutter/material.dart';

import 'api_client.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';

// 地点详情只消费服务端权威 Place/Visit read model；客户端负责严格解析与展示，不重算命名优先级或 Visit 可信状态。
// 初始页与分页都必须整页验证后再提交 UI state，避免半页数据被误当成可信历史。
class PlaceDetailPage extends StatefulWidget {
  const PlaceDetailPage({
    super.key,
    required this.api,
    required this.placeId,
  });

  final JiYiApiClient api;
  final String placeId;

  @override
  State<PlaceDetailPage> createState() => _PlaceDetailPageState();
}

class _PlaceDetailPageState extends State<PlaceDetailPage> {
  _PlaceDetailPlace? _place;
  final List<_PlaceDetailVisit> _visits = [];
  String? _nextCursor;
  String? _error;
  bool _loading = true;
  bool _loadingMore = false;

  @override
  void initState() {
    super.initState();
    _loadInitial();
  }

  Future<void> _loadInitial() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final response = await widget.api.getPlaceDetail(widget.placeId);
      final parsed = _PlaceDetailPayload.parse(response);
      if (mounted) {
        setState(() {
          _place = parsed.place;
          _visits
            ..clear()
            ..addAll(parsed.visits);
          _nextCursor = parsed.nextCursor;
          _error = null;
        });
      }
    } on Object catch (error) {
      if (mounted) setState(() => _error = _errorText(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadMore() async {
    final cursor = _nextCursor;
    if (cursor == null || _loadingMore) return;
    setState(() => _loadingMore = true);
    try {
      final response = await widget.api.getPlaceDetail(
        widget.placeId,
        cursor: cursor,
      );
      // 分页必须先完整验证整页协议，再一次性提交到 UI state；
      // 任何 Visit 或 next_cursor 字段异常都不能留下半页“看起来可信”的到访记录。
      final parsed = _PlaceDetailPayload.parse(response);
      final currentPlace = _place;
      if (currentPlace == null || parsed.place.id != currentPlace.id) {
        throw ProtocolException('服务端返回格式不正确');
      }
      if (mounted) {
        setState(() {
          _place = parsed.place;
          _visits.addAll(parsed.visits);
          _nextCursor = parsed.nextCursor;
          _error = null;
        });
      }
    } on Object catch (error) {
      if (mounted) setState(() => _error = _errorText(error));
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  String _errorText(Object error) {
    if (error is ApiException) return error.message;
    if (error is TransportException) return error.message;
    if (error is ProtocolException) return error.message;
    return '地点详情读取失败';
  }

  String _text(String? value, {String fallback = '—'}) {
    final normalized = value?.trim() ?? '';
    return normalized.isEmpty ? fallback : normalized;
  }

  String _line(String label, String? value, {String fallback = '—'}) {
    return '$label：${_text(value, fallback: fallback)}';
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(
        body: SafeArea(
          child: JiYiPageFrame(
            title: '地点详情',
            child: JiYiSectionCard(
              child: Padding(
                padding: EdgeInsets.symmetric(vertical: JiYiSpacing.xl),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    SizedBox.square(
                      dimension: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    SizedBox(width: JiYiSpacing.sm),
                    Text('正在读取地点详情…'),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    }

    if (_place == null) {
      return Scaffold(
        body: SafeArea(
          child: JiYiPageFrame(
            title: '地点详情',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                JiYiStatusBanner(
                  kind: JiYiStatusKind.error,
                  title: '无法读取地点详情',
                  message: _error ?? '地点详情读取失败',
                ),
                const SizedBox(height: JiYiSpacing.md),
                FilledButton(
                  onPressed: _loadInitial,
                  child: const Text('重试'),
                ),
              ],
            ),
          ),
        ),
      );
    }

    final place = _place!;
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('地点详情')),
      body: SafeArea(
        child: JiYiPageFrame(
          title: _text(place.name, fallback: '未命名地点'),
          subtitle: _text(place.address, fallback: '暂无地址信息'),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              JiYiSectionCard(
                leading: Icon(
                  Icons.place_outlined,
                  color: theme.colorScheme.primary,
                ),
                title: '地点概况',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(_line('类型', place.category)),
                    const SizedBox(height: JiYiSpacing.xs),
                    Text('累计到访：${place.visitCount} 次'),
                    const SizedBox(height: JiYiSpacing.xs),
                    Text(_line('首次到访', place.firstVisitedAt)),
                    const SizedBox(height: JiYiSpacing.xs),
                    Text(_line('最近到访', place.lastVisitedAt)),
                  ],
                ),
              ),
              const SizedBox(height: JiYiSpacing.md),
              JiYiSectionCard(
                title: '到访历史',
                subtitle: '只展示服务端保留的 Visit；“仍在更新”不等于已确认事实。',
                child: _visits.isEmpty
                    ? const JiYiEmptyState(
                        icon: Icons.history_toggle_off,
                        title: '还没有到访记录',
                        message: '这个地点当前没有可展示的 retained Visit。',
                      )
                    : Column(
                        children: [
                          for (var i = 0; i < _visits.length; i++) ...[
                            _VisitTile(visit: _visits[i]),
                            if (i != _visits.length - 1)
                              const Divider(height: JiYiSpacing.lg),
                          ],
                          if (_nextCursor != null) ...[
                            const SizedBox(height: JiYiSpacing.md),
                            OutlinedButton(
                              onPressed: _loadingMore ? null : _loadMore,
                              child: Text(_loadingMore ? '正在加载…' : '加载更多'),
                            ),
                          ],
                        ],
                      ),
              ),
              if (_error != null) ...[
                const SizedBox(height: JiYiSpacing.md),
                JiYiStatusBanner(
                  kind: JiYiStatusKind.error,
                  title: '部分到访记录加载失败',
                  message: _error!,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _VisitTile extends StatelessWidget {
  const _VisitTile({required this.visit});

  final _PlaceDetailVisit visit;

  String _line(String label, String? value) {
    final text = value?.trim() ?? '';
    return '$label：${text.isEmpty ? '—' : text}';
  }

  @override
  Widget build(BuildContext context) {
    final finalized = visit.visitFinalized;
    final theme = Theme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(
          finalized ? Icons.check_circle_outline : Icons.autorenew,
          color: finalized
              ? context.jiyiSemanticColors.success
              : theme.colorScheme.onSurfaceVariant,
        ),
        const SizedBox(width: JiYiSpacing.sm),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                finalized ? '已稳定的到访' : '仍在更新的到访',
                style: theme.textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: JiYiSpacing.xs),
              Text(_line('开始', visit.arrivedAt)),
              if (visit.leftAt != null) Text(_line('结束', visit.leftAt)),
              Text(_line('来源', visit.source)),
            ],
          ),
        ),
      ],
    );
  }
}


class _PlaceDetailPayload {
  const _PlaceDetailPayload({
    required this.place,
    required this.visits,
    required this.nextCursor,
  });

  final _PlaceDetailPlace place;
  final List<_PlaceDetailVisit> visits;
  final String? nextCursor;

  factory _PlaceDetailPayload.parse(Map<String, dynamic> raw) {
    final rawPlace = raw['place'];
    final rawVisits = raw['visits'];
    if (rawPlace is! Map<String, dynamic> || rawVisits is! List<dynamic>) {
      throw ProtocolException('服务端返回格式不正确');
    }

    final visits = <_PlaceDetailVisit>[];
    for (final item in rawVisits) {
      if (item is! Map<String, dynamic>) {
        throw ProtocolException('服务端返回格式不正确');
      }
      visits.add(_PlaceDetailVisit.parse(item));
    }

    final rawCursor = raw['next_cursor'];
    if (rawCursor != null && rawCursor is! String) {
      throw ProtocolException('服务端返回格式不正确');
    }
    final nextCursor = rawCursor as String?;
    if (nextCursor != null && nextCursor.trim().isEmpty) {
      throw ProtocolException('服务端返回格式不正确');
    }

    return _PlaceDetailPayload(
      place: _PlaceDetailPlace.parse(rawPlace),
      visits: List.unmodifiable(visits),
      nextCursor: nextCursor,
    );
  }
}

class _PlaceDetailPlace {
  const _PlaceDetailPlace({
    required this.id,
    required this.name,
    required this.nameSource,
    required this.address,
    required this.category,
    required this.visitCount,
    required this.firstVisitedAt,
    required this.lastVisitedAt,
  });

  final String id;
  final String name;
  final String nameSource;
  final String? address;
  final String? category;
  final int visitCount;
  final String? firstVisitedAt;
  final String? lastVisitedAt;

  factory _PlaceDetailPlace.parse(Map<String, dynamic> raw) {
    final id = _requiredText(raw['id']);
    final name = _requiredText(raw['name']);
    final nameSource = _requiredText(raw['name_source']);
    if (!const {'USER', 'AUTOMATIC', 'UNNAMED'}.contains(nameSource)) {
      throw ProtocolException('服务端返回格式不正确');
    }

    final visitCount = raw['visit_count'];
    if (visitCount is! int || visitCount < 0) {
      throw ProtocolException('服务端返回格式不正确');
    }

    return _PlaceDetailPlace(
      id: id,
      name: name,
      nameSource: nameSource,
      address: _nullableText(raw['address']),
      category: _nullableText(raw['category']),
      visitCount: visitCount,
      firstVisitedAt: _nullableIsoDateTime(raw['first_visited_at']),
      lastVisitedAt: _nullableIsoDateTime(raw['last_visited_at']),
    );
  }
}

class _PlaceDetailVisit {
  const _PlaceDetailVisit({
    required this.id,
    required this.arrivedAt,
    required this.leftAt,
    required this.durationSeconds,
    required this.confidence,
    required this.source,
    required this.finalizedAt,
    required this.visitFinalized,
  });

  final String id;
  final String arrivedAt;
  final String? leftAt;
  final int? durationSeconds;
  final double confidence;
  final String source;
  final String? finalizedAt;
  final bool visitFinalized;

  factory _PlaceDetailVisit.parse(Map<String, dynamic> raw) {
    final duration = raw['duration_seconds'];
    if (duration != null && (duration is! int || duration < 0)) {
      throw ProtocolException('服务端返回格式不正确');
    }

    final confidence = raw['confidence'];
    if (confidence is! num || !confidence.toDouble().isFinite) {
      throw ProtocolException('服务端返回格式不正确');
    }

    final finalized = raw['visit_finalized'];
    if (finalized is! bool) {
      throw ProtocolException('服务端返回格式不正确');
    }

    return _PlaceDetailVisit(
      id: _requiredText(raw['id']),
      arrivedAt: _requiredIsoDateTime(raw['arrived_at']),
      leftAt: _nullableIsoDateTime(raw['left_at']),
      durationSeconds: duration as int?,
      confidence: confidence.toDouble(),
      source: _requiredText(raw['source']),
      finalizedAt: _nullableIsoDateTime(raw['finalized_at']),
      visitFinalized: finalized,
    );
  }
}

String _requiredText(Object? value) {
  if (value is! String || value.trim().isEmpty) {
    throw ProtocolException('服务端返回格式不正确');
  }
  return value;
}

String? _nullableText(Object? value) {
  if (value == null) return null;
  if (value is! String) {
    throw ProtocolException('服务端返回格式不正确');
  }
  return value;
}

String _requiredIsoDateTime(Object? value) {
  if (value is! String || value.trim().isEmpty) {
    throw ProtocolException('服务端返回格式不正确');
  }
  try {
    DateTime.parse(value);
  } on FormatException {
    throw ProtocolException('服务端返回格式不正确');
  }
  return value;
}

String? _nullableIsoDateTime(Object? value) {
  if (value == null) return null;
  return _requiredIsoDateTime(value);
}
