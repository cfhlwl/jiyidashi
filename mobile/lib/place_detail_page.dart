import 'package:flutter/material.dart';

import 'amap_footprint_map.dart';
import 'amap_privacy_consent.dart';
import 'api_client.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_format.dart';
import 'ui/jiyi_tokens.dart';
import 'ui/jiyi_v3_components.dart';

// 地点详情只消费服务端权威 Place/Visit read model；客户端负责严格解析与展示，不重算命名优先级或 Visit 可信状态。
// 初始页与分页都必须整页验证后再提交 UI state，避免半页数据被误当成可信历史。
class PlaceDetailPage extends StatefulWidget {
  const PlaceDetailPage({
    super.key,
    required this.api,
    required this.placeId,
    this.amapPrivacyConsent,
  });

  final JiYiApiClient api;
  final String placeId;
  final AmapPrivacyConsentAuthority? amapPrivacyConsent;

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
  bool _offline = false;
  int _requestEpoch = 0;
  int? _displayedSessionVersion;
  String? _displayedOwnerId;
  bool _sessionRefreshScheduled = false;
  late final AmapPrivacyConsentAuthority _amapPrivacyConsent;
  Listenable? _mapPrivacyListenable;
  int _privacyReadEpoch = 0;
  bool _mapPrivacyAccepted = false;

  @override
  void initState() {
    super.initState();
    _amapPrivacyConsent =
        widget.amapPrivacyConsent ?? AmapPrivacyConsentStore();
    if (_amapPrivacyConsent is Listenable) {
      _mapPrivacyListenable = _amapPrivacyConsent as Listenable;
      _mapPrivacyListenable!.addListener(_handleMapPrivacyChanged);
    }
    _loadMapPrivacy();
    _loadInitial();
  }

  Future<void> _loadMapPrivacy() async {
    final readEpoch = ++_privacyReadEpoch;
    try {
      final accepted = await _amapPrivacyConsent.readAccepted();
      if (mounted && readEpoch == _privacyReadEpoch) {
        setState(() => _mapPrivacyAccepted = accepted);
      }
    } catch (_) {
      if (mounted && readEpoch == _privacyReadEpoch) {
        setState(() => _mapPrivacyAccepted = false);
      }
    }
  }

  void _handleMapPrivacyChanged() {
    final controller = _amapPrivacyConsent;
    if (controller is AmapPrivacyConsentController && mounted) {
      // The controller has already updated its fail-closed value before
      // notifying listeners. Apply that value synchronously so a revoked
      // consent can never leave the native map visible for another frame.
      setState(() => _mapPrivacyAccepted = controller.accepted);
    }
    _loadMapPrivacy();
  }

  Future<void> _acceptMapPrivacy() async {
    final accepted =
        await requestAmapPrivacyConsent(context, _amapPrivacyConsent);
    if (mounted && accepted) setState(() => _mapPrivacyAccepted = true);
  }

  Future<void> _loadInitial() async {
    final epoch = ++_requestEpoch;
    final sessionVersion = widget.api.sessionVersion;
    final ownerId = widget.api.authenticatedUserId;
    setState(() {
      _loading = true;
      _error = null;
      _offline = false;
      _place = null;
      _visits.clear();
      _nextCursor = null;
    });
    try {
      final response = await widget.api.getPlaceDetail(widget.placeId);
      final parsed = _PlaceDetailPayload.parse(response);
      if (!_requestCurrent(epoch, sessionVersion, ownerId)) return;
      if (parsed.place.id.toLowerCase() != widget.placeId.toLowerCase()) {
        throw ProtocolException('服务端返回格式不正确');
      }
      setState(() {
        _place = parsed.place;
        _visits.addAll(parsed.visits);
        _nextCursor = parsed.nextCursor;
        _displayedSessionVersion = sessionVersion;
        _displayedOwnerId = ownerId;
        _error = null;
        _offline = false;
      });
    } on Object catch (error) {
      if (_requestCurrent(epoch, sessionVersion, ownerId)) {
        setState(() {
          _error = _errorText(error);
          _offline = error is TransportException;
        });
      }
    } finally {
      if (_requestCurrent(epoch, sessionVersion, ownerId)) {
        setState(() => _loading = false);
      }
    }
  }

  Future<void> _loadMore() async {
    final cursor = _nextCursor;
    if (cursor == null || _loadingMore) return;
    final epoch = _requestEpoch;
    final sessionVersion = widget.api.sessionVersion;
    final ownerId = widget.api.authenticatedUserId;
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
      if (!_requestCurrent(epoch, sessionVersion, ownerId) ||
          currentPlace == null ||
          parsed.place.id.toLowerCase() != currentPlace.id.toLowerCase()) {
        throw ProtocolException('服务端返回格式不正确');
      }
      setState(() {
        _place = parsed.place;
        _visits.addAll(parsed.visits);
        _nextCursor = parsed.nextCursor;
        _displayedSessionVersion = sessionVersion;
        _displayedOwnerId = ownerId;
        _error = null;
        _offline = false;
      });
    } on Object catch (error) {
      if (_requestCurrent(epoch, sessionVersion, ownerId)) {
        setState(() {
          _error = _errorText(error);
          _offline = error is TransportException;
        });
      }
    } finally {
      if (_requestCurrent(epoch, sessionVersion, ownerId)) {
        setState(() => _loadingMore = false);
      }
    }
  }

  bool _requestCurrent(int epoch, int sessionVersion, String? ownerId) {
    return mounted &&
        epoch == _requestEpoch &&
        widget.api.sessionVersion == sessionVersion &&
        widget.api.authenticatedUserId == ownerId;
  }

  bool get _displayedDataIsCurrent =>
      _displayedSessionVersion == widget.api.sessionVersion &&
      _displayedOwnerId == widget.api.authenticatedUserId;

  void _scheduleSessionInvalidation() {
    if (_sessionRefreshScheduled) return;
    _sessionRefreshScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _sessionRefreshScheduled = false;
      if (!mounted || _displayedDataIsCurrent) return;
      _requestEpoch += 1;
      setState(() {
        _loading = true;
        _error = null;
        _offline = false;
        _place = null;
        _visits.clear();
        _nextCursor = null;
        _displayedSessionVersion = null;
        _displayedOwnerId = null;
      });
      _loadInitial();
    });
  }

  @override
  void dispose() {
    _mapPrivacyListenable?.removeListener(_handleMapPrivacyChanged);
    super.dispose();
  }

  String _errorText(Object error) {
    if (error is ApiException) return error.message;
    if (error is TransportException) return error.message;
    if (error is ProtocolException) return error.message;
    return '地点详情读取失败';
  }

  String? _placeCategoryLabel(String? value) {
    if (value == null || value.trim().isEmpty) return null;
    return switch (value) {
      'HOME' => '家',
      'OFFICE' => '办公室',
      'CAFE' => '咖啡店',
      'RESTAURANT' => '餐厅',
      'SHOP' => '商店',
      'SCHOOL' => '学校',
      'HOSPITAL' => '医院',
      'PARK' => '公园',
      'STATION' => '车站',
      _ => '其他地点',
    };
  }

  String _text(String? value, {String fallback = '—'}) {
    final normalized = value?.trim() ?? '';
    return normalized.isEmpty ? fallback : normalized;
  }

  String _line(String label, String? value, {String fallback = '—'}) {
    return '$label：${_text(value, fallback: fallback)}';
  }

  String _displayName(_PlaceDetailPlace place) {
    if (place.nameSource == 'UNNAMED' || place.name.trim().isEmpty) {
      return '未知地点';
    }
    return place.name;
  }

  Widget _mapState(_PlaceDetailPlace place) {
    if (place.latitude == null || place.longitude == null) {
      return const _PlaceMapState(
        key: ValueKey('place-map-no-coordinate-state'),
        icon: Icons.location_off_outlined,
        title: '暂无可用坐标',
        message: '这个地点没有完整坐标，地图不会猜测或补造位置。',
      );
    }

    return JiYiPlaceMap(
      key: const ValueKey('place-map-surface'),
      latitude: place.latitude,
      longitude: place.longitude,
      name: _displayName(place),
      address: place.address,
      privacyAccepted: _mapPrivacyAccepted,
    );
  }

  Widget _mapCard(_PlaceDetailPlace place) {
    final hasCoordinates = place.latitude != null && place.longitude != null;
    return V3SurfaceCard(
      key: const ValueKey('place-map-card'),
      padding: const EdgeInsets.all(JiYiSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(
              JiYiSpacing.xs,
              JiYiSpacing.xxs,
              JiYiSpacing.xs,
              JiYiSpacing.sm,
            ),
            child: V3SectionHeader(
              title: '地图位置',
              subtitle: '仅展示服务端已经形成的地点坐标。',
            ),
          ),
          _mapState(place),
          if (hasCoordinates && !_mapPrivacyAccepted) ...[
            const SizedBox(height: JiYiSpacing.sm),
            OutlinedButton.icon(
              key: const ValueKey('place-amap-privacy-accept'),
              onPressed: _acceptMapPrivacy,
              icon: const Icon(Icons.map_outlined),
              label: const Text('同意地图服务隐私说明并启用地图'),
            ),
          ],
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_place != null && !_displayedDataIsCurrent) {
      _scheduleSessionInvalidation();
      return V3PageScaffold(
        topBar: V3TopBar(
          title: '地点详情',
          onBack: () => Navigator.of(context).maybePop(),
        ),
        child: const V3StateSurface(
          variant: V3StateSurfaceVariant.loading,
          icon: Icons.sync_lock_outlined,
          title: '账号状态已变化',
          message: '正在清除旧账号的地点信息并重新读取。',
        ),
      );
    }
    if (_loading) {
      return V3PageScaffold(
        topBar: V3TopBar(
          title: '地点详情',
          onBack: () => Navigator.of(context).maybePop(),
        ),
        child: const V3StateSurface(
          variant: V3StateSurfaceVariant.loading,
          icon: Icons.place_outlined,
          title: '正在读取地点详情…',
          message: '正在读取服务端已经形成的地点与到访记录。',
        ),
      );
    }

    if (_place == null) {
      return V3PageScaffold(
        topBar: V3TopBar(
          title: '地点详情',
          onBack: () => Navigator.of(context).maybePop(),
        ),
        child: V3StateSurface(
          variant: _offline
              ? V3StateSurfaceVariant.offline
              : V3StateSurfaceVariant.error,
          icon: _offline ? Icons.cloud_off_outlined : Icons.place_outlined,
          title: _offline ? '当前离线' : '无法读取地点详情',
          message: _error ?? '地点详情读取失败',
          primaryAction: V3StateAction(
            label: '重试',
            icon: Icons.refresh,
            onPressed: _loadInitial,
          ),
        ),
      );
    }

    final place = _place!;
    final displayName = _displayName(place);
    return V3PageScaffold(
      topBar: V3TopBar(
        title: '地点详情',
        subtitle: displayName,
        onBack: () => Navigator.of(context).maybePop(),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          V3SurfaceCard(
            key: const ValueKey('place-summary-card'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                V3SectionHeader(
                  title: displayName,
                  subtitle: _text(place.address, fallback: '暂无地址信息'),
                ),
                const SizedBox(height: JiYiSpacing.md),
                Text(_line('类型', _placeCategoryLabel(place.category))),
                const SizedBox(height: JiYiSpacing.xs),
                Text('累计到访：${place.visitCount} 次'),
                const SizedBox(height: JiYiSpacing.xs),
                Text(_line(
                  '首次到访',
                  place.firstVisitedAt == null
                      ? null
                      : jiyiDisplayDateTime(place.firstVisitedAt!),
                )),
                const SizedBox(height: JiYiSpacing.xs),
                Text(_line(
                  '最近到访',
                  place.lastVisitedAt == null
                      ? null
                      : jiyiDisplayDateTime(place.lastVisitedAt!),
                )),
              ],
            ),
          ),
          const SizedBox(height: JiYiSpacing.sectionGap),
          _mapCard(place),
          const SizedBox(height: JiYiSpacing.sectionGap),
          V3SurfaceCard(
            key: const ValueKey('place-visits-card'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const V3SectionHeader(
                  title: '到访历史',
                  subtitle: '只展示已经形成的到访记录；“仍在更新”不等于已确认事实。',
                ),
                const SizedBox(height: JiYiSpacing.md),
                if (_visits.isEmpty)
                  const V3StateSurface(
                    variant: V3StateSurfaceVariant.empty,
                    icon: Icons.history_toggle_off,
                    title: '还没有到访记录',
                    message: '这个地点当前还没有可展示的到访记录。',
                  )
                else ...[
                  for (var i = 0; i < _visits.length; i++) ...[
                    _VisitTile(visit: _visits[i]),
                    if (i != _visits.length - 1)
                      const Divider(height: JiYiSpacing.lg),
                  ],
                  if (_nextCursor != null) ...[
                    const SizedBox(height: JiYiSpacing.md),
                    OutlinedButton(
                      key: const ValueKey('place-load-more'),
                      onPressed: _loadingMore ? null : _loadMore,
                      child: Text(_loadingMore ? '正在加载…' : '加载更多'),
                    ),
                  ],
                ],
              ],
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: JiYiSpacing.sectionGap),
            JiYiStatusBanner(
              kind: _offline ? JiYiStatusKind.warning : JiYiStatusKind.error,
              title: _offline ? '部分记录暂时离线' : '部分到访记录加载失败',
              message: _error!,
            ),
          ],
        ],
      ),
    );
  }
}

class _PlaceMapState extends StatelessWidget {
  const _PlaceMapState({
    super.key,
    required this.icon,
    required this.title,
    required this.message,
  });

  final IconData icon;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      constraints: const BoxConstraints(minHeight: 180),
      padding: const EdgeInsets.all(JiYiSpacing.lg),
      decoration: BoxDecoration(
        color: JiYiSurfaceRoles.soft,
        borderRadius: BorderRadius.circular(JiYiRadius.card),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: JiYiIconSize.large, color: theme.colorScheme.primary),
          const SizedBox(height: JiYiSpacing.sm),
          Text(
            title,
            textAlign: TextAlign.center,
            style: theme.textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: JiYiSpacing.xs),
          Text(
            message,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
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
              Text(_line('开始', jiyiDisplayDateTime(visit.arrivedAt))),
              if (visit.leftAt != null) Text(_line('结束', jiyiDisplayDateTime(visit.leftAt!))),
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
    required this.latitude,
    required this.longitude,
    required this.address,
    required this.category,
    required this.visitCount,
    required this.firstVisitedAt,
    required this.lastVisitedAt,
  });

  final String id;
  final String name;
  final String nameSource;
  final double? latitude;
  final double? longitude;
  final String? address;
  final String? category;
  final int visitCount;
  final String? firstVisitedAt;
  final String? lastVisitedAt;

  factory _PlaceDetailPlace.parse(Map<String, dynamic> raw) {
    final id = _requiredText(raw['id']);
    final rawName = raw['name'];
    if (rawName is! String) {
      throw ProtocolException('服务端返回格式不正确');
    }
    final name = rawName;
    final nameSource = _requiredText(raw['name_source']);
    if (!const {'USER', 'AUTOMATIC', 'UNNAMED'}.contains(nameSource)) {
      throw ProtocolException('服务端返回格式不正确');
    }
    if (nameSource != 'UNNAMED' && name.trim().isEmpty) {
      throw ProtocolException('服务端返回格式不正确');
    }

    final visitCount = raw['visit_count'];
    if (visitCount is! int || visitCount < 0) {
      throw ProtocolException('服务端返回格式不正确');
    }
    final latitude = _nullableCoordinate(raw['latitude'], latitudeAxis: true);
    final longitude = _nullableCoordinate(raw['longitude'], latitudeAxis: false);
    if ((latitude == null) != (longitude == null)) {
      throw ProtocolException('服务端返回格式不正确');
    }

    return _PlaceDetailPlace(
      id: id,
      name: name,
      nameSource: nameSource,
      latitude: latitude,
      longitude: longitude,
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

double? _nullableCoordinate(Object? value, {required bool latitudeAxis}) {
  if (value == null) return null;
  if (value is! num || !value.isFinite) {
    throw ProtocolException('服务端返回格式不正确');
  }
  final coordinate = value.toDouble();
  final max = latitudeAxis ? 90.0 : 180.0;
  if (coordinate < -max || coordinate > max) {
    throw ProtocolException('服务端返回格式不正确');
  }
  return coordinate;
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
