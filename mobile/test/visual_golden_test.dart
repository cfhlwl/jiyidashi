import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/amap_footprint_map.dart';
import 'package:jiyidashi/amap_privacy_consent.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/footprint_models.dart';
import 'package:jiyidashi/media_presentation_cache.dart';
import 'package:jiyidashi/memory_detail_page.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/onboarding_flow.dart';
import 'package:jiyidashi/place_detail_page.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:jiyidashi/today_footprint_page.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:jiyidashi/v2/family_page.dart';
import 'package:jiyidashi/v2/graph_page.dart';
import 'package:jiyidashi/v2/life_page.dart';
import 'package:jiyidashi/v2/life_event_detail_page.dart';
import 'package:jiyidashi/v2/life_stage_detail_page.dart';
import 'package:jiyidashi/v2/memoirs_page.dart';
import 'package:jiyidashi/v2/people_page.dart';
import 'package:jiyidashi/v2/person_detail_page.dart';

import 'v2_test_api.dart';

// [人工注释][CI-005] Golden 只冻结当前产品渲染结果，不为“好测试”改业务组件；
// 统一窗口、DPR、locale 与主题，Linux CI 是首阶段唯一权威像素基线。
const _goldenSize = Size(390, 844);
const _goldenFontFamily = 'JiYi Golden CJK';
const _captureDeterministicQueryPreview =
    bool.fromEnvironment('DETERMINISTIC_QUERY_VISUAL_PREVIEW');

const _goldenCacheVersion =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

class _GoldenAmapConsent implements AmapPrivacyConsentAuthority {
  _GoldenAmapConsent(this.accepted);

  bool accepted;

  @override
  Future<void> accept() async => accepted = true;

  @override
  Future<bool> readAccepted() async => accepted;

  @override
  Future<void> revoke() async => accepted = false;
}

Widget _goldenLocalPhoto(
  BuildContext context,
  File file,
  BoxFit fit,
) {
  final scheme = Theme.of(context).colorScheme;
  return Semantics(
    label: '本地照片视觉测试样本',
    child: DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            scheme.primaryContainer,
            scheme.tertiaryContainer,
          ],
        ),
      ),
      child: Stack(
        fit: StackFit.expand,
        children: [
          Align(
            alignment: const Alignment(0, -0.22),
            child: Icon(
              Icons.wb_sunny_outlined,
              size: 42,
              color: scheme.onPrimaryContainer.withValues(alpha: 0.78),
            ),
          ),
          Align(
            alignment: const Alignment(0, 0.42),
            child: Icon(
              Icons.landscape_outlined,
              size: 92,
              color: scheme.onTertiaryContainer.withValues(alpha: 0.88),
            ),
          ),
        ],
      ),
    ),
  );
}

Widget _goldenFootprintMap(
  BuildContext context,
  JiYiAmapConfig config,
  List<FootprintVisit> visits,
  int selectedIndex,
  ValueChanged<int> onSelected,
  bool interactive,
) {
  final scheme = Theme.of(context).colorScheme;
  return DecoratedBox(
    decoration: BoxDecoration(
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [
          scheme.surfaceContainerLow,
          scheme.primaryContainer.withValues(alpha: 0.72),
        ],
      ),
    ),
    child: Stack(
      children: [
        Positioned.fill(
          child: CustomPaint(
            painter: _GoldenMapLinePainter(
              color: scheme.primary.withValues(alpha: 0.35),
            ),
          ),
        ),
        for (var index = 0; index < visits.length; index++)
          Align(
            alignment: Alignment(
              visits.length == 1 ? 0 : -0.72 + (1.44 * index / (visits.length - 1)),
              visits.length == 1 ? 0 : (index.isEven ? -0.28 : 0.3),
            ),
            child: GestureDetector(
              onTap: interactive ? () => onSelected(index) : null,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  CircleAvatar(
                    radius: index == selectedIndex ? 19 : 16,
                    backgroundColor: index == selectedIndex
                        ? scheme.primary
                        : scheme.surface,
                    foregroundColor: index == selectedIndex
                        ? scheme.onPrimary
                        : scheme.primary,
                    child: Text('${index + 1}'),
                  ),
                  const SizedBox(height: 4),
                  Container(
                    constraints: const BoxConstraints(maxWidth: 120),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 4,
                    ),
                    decoration: BoxDecoration(
                      color: scheme.surface.withValues(alpha: 0.92),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      visits[index].placeName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    ),
  );
}

Widget _goldenPlaceMap(
  BuildContext context,
  JiYiAmapConfig config,
  double latitude,
  double longitude,
  String name,
  String? address,
) {
  final scheme = Theme.of(context).colorScheme;
  return DecoratedBox(
    decoration: BoxDecoration(
      gradient: LinearGradient(
        colors: [
          scheme.surfaceContainerLow,
          scheme.primaryContainer.withValues(alpha: 0.75),
        ],
      ),
    ),
    child: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          CircleAvatar(
            radius: 21,
            backgroundColor: scheme.primary,
            foregroundColor: scheme.onPrimary,
            child: const Icon(Icons.place),
          ),
          const SizedBox(height: 8),
          Text(
            name,
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w800,
                ),
          ),
          if (address != null && address.trim().isNotEmpty)
            Text(
              address,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.bodySmall,
            ),
        ],
      ),
    ),
  );
}

class _GoldenMapLinePainter extends CustomPainter {
  const _GoldenMapLinePainter({required this.color});

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.2;
    final path = Path()
      ..moveTo(size.width * 0.16, size.height * 0.38)
      ..cubicTo(
        size.width * 0.38,
        size.height * 0.15,
        size.width * 0.58,
        size.height * 0.74,
        size.width * 0.84,
        size.height * 0.46,
      );
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(_GoldenMapLinePainter oldDelegate) =>
      oldDelegate.color != color;
}

Future<LocalMediaCache> _seedGoldenMediaCache(
  String ownerUserId, {
  String mediaId = v2MediaId,
}) async {
  final root = await Directory.systemTemp.createTemp('jiyi-golden-media-');
  addTearDown(() => root.delete(recursive: true));
  final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
  await cache.putBytes(
    ownerUserId: ownerUserId,
    mediaId: mediaId,
    cacheVersion: _goldenCacheVersion,
    bytes: const <int>[1, 2, 3, 4],
  );
  cache.markAuthorityValidated(
    ownerUserId: ownerUserId,
    mediaId: mediaId,
  );
  return cache;
}

// [人工注释][CI-005] Golden 必须显式加载仓库内固定版本的 CJK 字体；禁止依赖 Runner 系统字体，
// 否则 Ubuntu 镜像变化或 flutter_test 缺字会把中文排版回归伪装成稳定结果。
Future<void> _loadGoldenFont() async {
  final bytes = await File('test/fonts/JiYiGoldenCJK-Regular.ttf')
      .readAsBytes();
  final loader = FontLoader(_goldenFontFamily)
    ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
  await loader.load();
}

// [人工注释][CI-005] Flutter Icons.* 的 IconData 固定使用 `MaterialIcons` family；
// Golden 必须显式注册仓库内的 Flutter 3.47.4 MaterialIcons 字体，否则图标会退化成缺字方框。
Future<void> _loadMaterialIconsFont() async {
  final bytes = await File('test/fonts/MaterialIcons-Regular.otf')
      .readAsBytes();
  final loader = FontLoader('MaterialIcons')
    ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
  await loader.load();
}

// Golden 复用生产 Theme；这里只注入仓库固定 CJK 测试字体，禁止再次复制产品色/布局 token。
ThemeData _goldenTheme({bool elderMode = false}) => JiYiTheme.light(
      fontFamily: _goldenFontFamily,
      elderMode: elderMode,
    );

class _GoldenApi extends JiYiApiClient {
  _GoldenApi({
    this.privacyStatus = const {
      'recording_paused': false,
      'paused_until': null,
    },
    this.privacyError,
  }) : super(baseUrl: 'http://golden.invalid/v1') {
    accessToken = 'golden-token';
    authenticatedUserId = '00000000-0000-4000-8000-000000000001';
  }

  final Map<String, dynamic> privacyStatus;
  final ApiException? privacyError;

  @override
  Future<Map<String, dynamic>> getProfile() async => {
    'id': authenticatedUserId,
    'nickname': '测试用户',
    'email': 'golden@example.com',
    'timezone': 'Asia/Shanghai',
    'locale': 'zh-CN',
    'elder_mode_enabled': false,
  };

  @override
  Future<Map<String, dynamic>> queryMemory(String question) async => {
    'answer': '护照最后记录在书房抽屉。',
    'can_answer': true,
    'certainty': 'confirmed',
    'reason': null,
    'intent': 'FIND_OBJECT',
    'evidence': [
      {
        'kind': 'OBJECT_LOCATION',
        'id': '33333333-3333-4333-8333-333333333333',
        'source_type': 'USER_TEXT',
        'memory_source_id': '44444444-4444-4444-8444-444444444444',
        'occurred_at': '2026-09-20T02:20:00Z',
        'excerpt': '护照放在书房抽屉。',
        'confidence': 1.0,
        'provenance': 'ORIGINAL_SOURCE',
      }
    ],
    'memory_ids': ['55555555-5555-4555-8555-555555555555'],
  };

  @override
  Future<Map<String, dynamic>> getTodayFootprint() async => {
    'timezone': 'Asia/Shanghai',
    'day': '2026-09-20',
    'visits': [
      {
        'id': '11111111-1111-4111-8111-111111111111',
        'place_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        'place_name': '书房',
        'place_latitude': 31.2304,
        'place_longitude': 121.4737,
        'place_address': '上海市静安区家中书房',
        'place_category': 'HOME',
        'arrived_at': '2026-09-19T23:10:00Z',
        'left_at': '2026-09-20T00:00:00Z',
        'arrived_at_local': '2026-09-20T07:10:00+08:00',
        'left_at_local': '2026-09-20T08:00:00+08:00',
        'confidence': 0.94,
        'visit_source': 'LOCATION_CLUSTER',
        'visit_finalized': true,
      },
      {
        'id': '22222222-2222-4222-8222-222222222222',
        'place_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        'place_name': '公司',
        'place_latitude': 31.2243,
        'place_longitude': 121.4768,
        'place_address': '上海市静安区测试路 1 号',
        'place_category': 'OFFICE',
        'arrived_at': '2026-09-20T00:35:00Z',
        'left_at': null,
        'arrived_at_local': '2026-09-20T08:35:00+08:00',
        'left_at_local': null,
        'confidence': 0.88,
        'visit_source': 'LOCATION_CLUSTER',
        'visit_finalized': false,
      },
    ],
  };

  @override
  Future<Map<String, dynamic>> getTimelineEvents({
    int limit = 30,
    String? cursor,
    String? day,
  }) async => {
        'timezone': 'Asia/Shanghai',
        'day': day,
        'items': day == '2026-09-20'
            ? [
                {
                  'kind': 'MEMORY',
                  'id': v2MemoryId,
                  'occurred_at': '2026-09-20T01:15:00Z',
                  'ended_at': null,
                  'place_id': v2PlaceId,
                  'place_name': '上海办公室',
                  'memory_type': 'PHOTO',
                  'title': '晨光里的白板',
                  'content': '把第一版产品方向写满了整块白板。',
                  'source_type': 'USER_PHOTO',
                  'is_confirmed': true,
                  'media_id': v2MediaId,
                  'confidence': 1.0,
                  'visit_source': null,
                  'visit_finalized': null,
                },
              ]
            : const <Map<String, dynamic>>[],
        'next_cursor': null,
      };

  @override
  Future<Map<String, dynamic>> getRecordingHealth({
    Map<String, dynamic>? clientState,
  }) async {
    final paused = privacyStatus['recording_paused'] == true;
    final status = paused ? 'PAUSED' : 'HEALTHY';
    final reason = paused ? 'PRIVACY_PAUSED' : 'RECENT_CAPTURE_AND_ACK';
    return <String, dynamic>{
      'health': <String, dynamic>{
        'status': status,
        'status_reason': reason,
        'automatic_enabled': !paused,
        'privacy_paused': paused,
        'permission_state': paused ? null : 'BACKGROUND',
        'location_services_state': 'ON',
        'background_runtime_state': 'ELIGIBLE',
        'battery_optimization_state': 'OPTIMIZED',
        'native_producer_state': paused ? 'STOPPED' : 'RUNNING',
        'native_queue_depth': 0,
        'native_queue_capacity': 1000,
        'native_oldest_pending_at': null,
        'sqlite_queue_depth': 0,
        'capacity_pressure': false,
        'last_fix_at': paused ? null : '2026-09-20T02:30:00Z',
        'last_enqueue_at': null,
        'last_handoff_at': null,
        'last_upload_attempt_at': null,
        'last_upload_success_at': null,
        'last_server_ack_at': paused ? null : '2026-09-20T02:31:00Z',
        'last_visit_at': null,
        'delivery_failure_count': 0,
        'last_delivery_error_code': null,
        'recovery_pending': false,
        'recording_gap_state': paused ? 'UNKNOWN' : 'NONE',
        'updated_at': '2026-09-20T02:32:00Z',
      },
      'today': <String, dynamic>{
        'local_day': '2026-09-20',
        'timezone': 'Asia/Shanghai',
        'first_observed_at': null,
        'last_observed_at': null,
        'trusted_location_sample_count': paused ? 0 : 12,
        'visit_count': paused ? 0 : 2,
        'memory_count': 1,
        'covered_duration_seconds': paused ? 0 : 12600,
        'known_gap_duration_seconds': 0,
        'largest_known_gap_seconds': 0,
        'coverage_state': paused ? 'UNKNOWN' : 'HEALTHY',
        'has_capacity_pressure': false,
        'has_recorded_gap': false,
        'has_unexplained_gap': false,
        'recent_gaps': <Object?>[],
      },
      'aggregates': <String, dynamic>{
        'healthy_days_7d': paused ? 0 : 6,
        'healthy_days_30d': paused ? 0 : 24,
        'evidence_days_7d': 7,
        'evidence_days_30d': 28,
        'gap_hours_7d': null,
        'gap_hours_30d': null,
        'bounded_gap_hours_7d': 0.0,
        'bounded_gap_hours_30d': 0.0,
        'days_with_capacity_pressure': null,
        'days_with_permission_block': null,
        'current_capacity_pressure': false,
        'current_permission_block': false,
      },
      'recent_gaps': <Object?>[],
      'active_gap_reasons': paused ? <String>['PRIVACY_PAUSED'] : <String>[],
      'server_observed_at': '2026-09-20T02:32:00Z',
      'native_state_observed': true,
    };
  }

  @override
  Future<Map<String, dynamic>> getPrivacyStatus() async {
    final error = privacyError;
    if (error != null) throw error;
    return privacyStatus;
  }
}

class _GoldenTimelineApi extends _GoldenApi {
  @override
  Future<Map<String, dynamic>> getTimelineEvents({
    int limit = 30,
    String? cursor,
    String? day,
  }) async => {
        'timezone': 'Asia/Shanghai',
        'day': null,
        'items': [
          {
            'kind': 'MEMORY',
            'id': v2MemoryId,
            'occurred_at': '2025-03-01T09:30:00Z',
            'ended_at': null,
            'place_id': v2PlaceId,
            'place_name': '上海办公室',
            'memory_type': 'PHOTO',
            'title': '第一次产品讨论',
            'content': '把第一版产品方向写满了整块白板。',
            'source_type': 'USER_PHOTO',
            'is_confirmed': true,
            'media_id': v2MediaId,
            'confidence': 1.0,
            'visit_source': null,
            'visit_finalized': null,
          },
          {
            'kind': 'VISIT',
            'id': '33333333-3333-4333-8333-333333333333',
            'occurred_at': '2025-02-28T05:20:00Z',
            'ended_at': '2025-02-28T06:40:00Z',
            'place_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            'place_name': '周末咖啡店',
            'memory_type': null,
            'title': null,
            'content': null,
            'source_type': null,
            'is_confirmed': null,
            'confidence': 0.96,
            'visit_source': 'LOCATION_CLUSTER',
            'visit_finalized': true,
          },
        ],
        'next_cursor': null,
      };
}

class _GoldenEmptyTimelineApi extends _GoldenApi {
  @override
  Future<Map<String, dynamic>> getTimelineEvents({
    int limit = 30,
    String? cursor,
    String? day,
  }) async => {
        'timezone': 'Asia/Shanghai',
        'day': null,
        'items': const <Map<String, dynamic>>[],
        'next_cursor': null,
      };
}

class _GoldenOfflineTimelineApi extends _GoldenApi {
  @override
  Future<Map<String, dynamic>> getTimelineEvents({
    int limit = 30,
    String? cursor,
    String? day,
  }) async {
    throw TransportException('网络连接失败');
  }
}

class _GoldenFamilyApi extends _GoldenApi {
  static const memberId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    if (method == 'GET' && path == '/family') {
      return {
        'family_id': 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        'current_user_role': 'OWNER',
        'members': [
          {
            'user_id': authenticatedUserId,
            'role': 'OWNER',
            'created_at': '2026-09-01T00:00:00Z',
          },
          {
            'user_id': memberId,
            'role': 'MEMBER',
            'created_at': '2026-09-02T00:00:00Z',
          },
        ],
      };
    }
    if (method == 'GET' && path == '/family/permissions') {
      return [
        {
          'grantee_user_id': memberId,
          'permissions': ['VIEW_MEMORY', 'VIEW_PHOTOS'],
        },
      ];
    }
    if (method == 'GET' && path == '/family/members/$memberId/photos') {
      return [
        {
          'media_id': v2MediaId,
          'content_type': 'image/jpeg',
          'size_bytes': 4,
          'created_at': '2026-09-20T01:15:00Z',
          'completed_at': '2026-09-20T01:15:01Z',
          'cache_version': _goldenCacheVersion,
        },
      ];
    }
    if (method == 'GET' &&
        path == '/family/members/$memberId/current-location') {
      return {
        'resource_owner_user_id': memberId,
        'latitude': 31.2243,
        'longitude': 121.4768,
        'accuracy': 8.0,
        'recorded_at': '2026-09-20T08:35:00+08:00',
        'fresh_until': '2030-09-20T09:00:00+08:00',
      };
    }
    if (method == 'GET' &&
        path == '/family/members/$memberId/today/footprint') {
      return {
        'timezone': 'Asia/Shanghai',
        'day': '2026-09-20',
        'visits': [
          {
            'id': '77777777-7777-4777-8777-777777777777',
            'place_id': '88888888-8888-4888-8888-888888888888',
            'place_name': '滨江公园',
            'place_latitude': 31.2391,
            'place_longitude': 121.4972,
            'place_address': '上海市浦东新区滨江步道',
            'place_category': 'PARK',
            'arrived_at': '2026-09-20T01:00:00Z',
            'left_at': '2026-09-20T02:10:00Z',
            'arrived_at_local': '2026-09-20T09:00:00+08:00',
            'left_at_local': '2026-09-20T10:10:00+08:00',
            'confidence': 0.96,
            'visit_source': 'LOCATION_CLUSTER',
            'visit_finalized': true,
          },
        ],
      };
    }
    if (method == 'GET' &&
        path == '/family/members/$memberId/memories?limit=8') {
      return [
        {
          'memory_id': '99999999-9999-4999-8999-999999999999',
          'memory_type': 'NOTE',
          'title': '周末一起散步',
          'content': '傍晚沿江走了一段，风很舒服。',
          'occurred_at': '2026-09-20T02:00:00Z',
          'source_type': 'USER_TEXT',
          'is_confirmed': true,
          'edit_revision': 0,
          'created_at': '2026-09-20T02:00:00Z',
        },
      ];
    }
    throw ApiException(404, 'NOT_FOUND');
  }
}

class _GoldenHistoricalQueryApi extends _GoldenApi {
  @override
  Future<Map<String, dynamic>> queryMemory(String question) async => {
        'answer': '9 月 20 日上午去了滨江公园，之后到了公司。',
        'can_answer': true,
        'certainty': 'confirmed',
        'reason': null,
        'intent': 'DATE_FOOTPRINT_QUERY',
        'evidence': [
          {
            'kind': 'VISIT',
            'id': '77777777-7777-4777-8777-777777777777',
            'source_type': 'LOCATION_CLUSTER',
            'occurred_at': '2026-09-20T01:00:00Z',
            'excerpt': '滨江公园 · 09:00–10:10',
            'confidence': 0.96,
            'provenance': 'ORIGINAL_SOURCE',
          },
        ],
        'memory_ids': const <String>[],
        'day_footprint': {
          'timezone': 'Asia/Shanghai',
          'day': '2026-09-20',
          'visits': [
            {
              'id': '77777777-7777-4777-8777-777777777777',
              'place_id': '88888888-8888-4888-8888-888888888888',
              'place_name': '滨江公园',
              'place_latitude': 31.2391,
              'place_longitude': 121.4972,
              'place_address': '上海市浦东新区滨江步道',
              'place_category': 'PARK',
              'arrived_at': '2026-09-20T01:00:00Z',
              'left_at': '2026-09-20T02:10:00Z',
              'arrived_at_local': '2026-09-20T09:00:00+08:00',
              'left_at_local': '2026-09-20T10:10:00+08:00',
              'confidence': 0.96,
              'visit_source': 'LOCATION_CLUSTER',
              'visit_finalized': true,
            },
            {
              'id': 'aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa',
              'place_id': 'bbbbbbbb-1111-4111-8111-bbbbbbbbbbbb',
              'place_name': '公司',
              'place_latitude': 31.2243,
              'place_longitude': 121.4768,
              'place_address': '上海市静安区测试路 1 号',
              'place_category': 'OFFICE',
              'arrived_at': '2026-09-20T03:00:00Z',
              'left_at': null,
              'arrived_at_local': '2026-09-20T11:00:00+08:00',
              'left_at_local': null,
              'confidence': 0.92,
              'visit_source': 'LOCATION_CLUSTER',
              'visit_finalized': false,
            },
          ],
        },
      };
}

class _GoldenMemoryDetailApi extends _GoldenApi {
  @override
  Future<Map<String, dynamic>> getMemory(String memoryId) async => {
    'id': v2MemoryId,
    'user_id': authenticatedUserId,
    'memory_type': 'PHOTO',
    'title': '第一次产品讨论',
    'content': '那天我们在办公室把第一版产品方向写满了整块白板。',
    'occurred_at': '2025-03-01T01:00:00Z',
    'source_type': 'USER_PHOTO',
    'confidence': 1.0,
    'place_id': v2PlaceId,
    'latitude': null,
    'longitude': null,
    'is_confirmed': true,
    'metadata_json': const <String, dynamic>{'media_id': v2MediaId},
    'edit_revision': 3,
    'edited_at': null,
    'created_at': '2025-03-01T01:00:00Z',
  };

  @override
  Future<Map<String, dynamic>> getPlaceDetail(
    String placeId, {
    int limit = 50,
    String? cursor,
  }) async => {
    'place': {
      'id': v2PlaceId,
      'name': '上海办公室',
      'name_source': 'USER',
      'address': '上海市测试路 1 号',
      'latitude': 31.2243,
      'longitude': 121.4768,
      'category': 'OFFICE',
      'visit_count': 5,
      'first_visited_at': '2025-01-01T00:00:00Z',
      'last_visited_at': '2026-09-20T00:00:00Z',
    },
    'visits': const <Map<String, dynamic>>[],
    'next_cursor': null,
  };
}

class _GoldenPlaceDetailApi extends JiYiApiClient {
  _GoldenPlaceDetailApi() : super(baseUrl: 'http://golden-place.invalid/v1') {
    accessToken = 'golden-token';
    authenticatedUserId = '00000000-0000-4000-8000-000000000001';
  }

  @override
  Future<Map<String, dynamic>> getPlaceDetail(
    String placeId, {
    int limit = 50,
    String? cursor,
  }) async {
    return {
      'place': {
        'id': 'place-golden-1',
        'name': '常去的咖啡店',
        'name_source': 'USER',
        'address': '上海市静安区测试路 88 号',
        'category': 'CAFE',
        'visit_count': 8,
        'first_visited_at': '2026-09-01T01:10:00Z',
        'last_visited_at': '2026-09-20T03:30:00Z',
      },
      'visits': [
        {
          'id': 'visit-golden-finalized',
          'arrived_at': '2026-09-20T02:20:00Z',
          'left_at': '2026-09-20T03:30:00Z',
          'duration_seconds': 4200,
          'confidence': 0.96,
          'source': 'GPS',
          'finalized_at': '2026-09-20T04:00:00Z',
          'visit_finalized': true,
        },
        {
          'id': 'visit-golden-mutable',
          'arrived_at': '2026-09-19T09:10:00Z',
          'left_at': null,
          'duration_seconds': null,
          'confidence': 0.82,
          'source': 'GPS',
          'finalized_at': null,
          'visit_finalized': false,
        },
      ],
      'next_cursor': 'golden-next-page',
    };
  }
}

// Golden tests must not depend on an unregistered platform channel. Native platform policy
// is covered separately by Flutter bridge tests, Android JVM tests and iOS RunnerTests.
class _GoldenQueue extends OfflineQueueStore {
  @override
  Future<int> countAwaitingDelivery(String ownerUserId) async => 0;

  @override
  Future<void> close() async {}
}

Future<Key> _pumpSurface(
  WidgetTester tester,
  Widget child, {
  bool elderMode = false,
}) async {
  tester.view.physicalSize = _goldenSize;
  tester.view.devicePixelRatio = 1.0;
  tester.binding.platformDispatcher.localeTestValue = const Locale('zh', 'CN');
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
    tester.binding.platformDispatcher.clearLocaleTestValue();
  });

  const key = ValueKey<String>('golden-surface');
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: _goldenTheme(elderMode: elderMode),
      home: JiYiAmapPresentationScope(
        config: const JiYiAmapConfig(
          androidKey: 'golden-amap-key',
          platformOverride: TargetPlatform.android,
          appEnv: 'development',
        ),
        footprintBuilder: _goldenFootprintMap,
        placeBuilder: _goldenPlaceMap,
        child: LocalMediaPresentationScope(
          renderer: _goldenLocalPhoto,
          child: RepaintBoundary(key: key, child: child),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
  return key;
}

Widget _goldenNavigationShell({
  required int selectedIndex,
  required Widget child,
  bool showCapture = true,
}) {
  return Scaffold(
    body: SafeArea(child: child),
    floatingActionButton: showCapture
        ? FloatingActionButton.extended(
            onPressed: () {},
            icon: const Icon(Icons.add),
            label: const Text('记一下'),
          )
        : null,
    bottomNavigationBar: NavigationBar(
      selectedIndex: selectedIndex,
      onDestinationSelected: (_) {},
      destinations: const [
        NavigationDestination(
          icon: Icon(Icons.today_outlined),
          selectedIcon: Icon(Icons.today),
          label: '今天',
        ),
        NavigationDestination(
          icon: Icon(Icons.auto_stories_outlined),
          selectedIcon: Icon(Icons.auto_stories),
          label: '记忆',
        ),
        NavigationDestination(
          icon: Icon(Icons.route_outlined),
          selectedIcon: Icon(Icons.route),
          label: '人生',
        ),
        NavigationDestination(
          icon: Icon(Icons.family_restroom_outlined),
          selectedIcon: Icon(Icons.family_restroom),
          label: '家庭',
        ),
        NavigationDestination(
          icon: Icon(Icons.person_outline),
          selectedIcon: Icon(Icons.person),
          label: '我的',
        ),
      ],
    ),
  );
}

Future<Key> _pumpGoldenToday(
  WidgetTester tester, {
  bool mapAccepted = false,
}) async {
  final api = _GoldenApi();
  final cache = await _seedGoldenMediaCache(api.authenticatedUserId!);
  return _pumpSurface(
    tester,
    _goldenNavigationShell(
      selectedIndex: 0,
      child: TodayPage(
        api: api,
        mediaCache: cache,
        amapPrivacyConsent: _GoldenAmapConsent(mapAccepted),
      ),
    ),
  );
}

Future<Key> _pumpGoldenMemoryQuery(WidgetTester tester) {
  return _pumpSurface(
    tester,
    _goldenNavigationShell(
      selectedIndex: 1,
      child: MemoryQueryPage(api: _GoldenApi()),
    ),
  );
}

Future<Key> _pumpGoldenProfile(
  WidgetTester tester, {
  _GoldenApi? api,
  bool mapAccepted = false,
}) {
  final resolvedApi = api ?? _GoldenApi();
  return _pumpSurface(
    tester,
    _goldenNavigationShell(
      selectedIndex: 4,
      showCapture: false,
      child: ProfilePage(
        api: resolvedApi,
        onLogout: () {},
        onAccountDeleteIntentConfirmed: () async {},
        onAccountDeleted: () async {},
        offlineQueue: _GoldenQueue(),
        amapPrivacyConsent: _GoldenAmapConsent(mapAccepted),
      ),
    ),
  );
}

void main() {
  // #163: committed V2 baselines are generated from the same Flutter 3.47.4
  // deterministic CJK-font harness used by the existing mobile visual gate.
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    await _loadGoldenFont();
    await _loadMaterialIconsFont();
  });

  testWidgets('golden: login', (tester) async {
    // [人工注释][CI-005] 登录页使用真实 AuthPage 静态初始态，禁止网络调用和截图后处理。
    final key = await _pumpSurface(
      tester,
      AuthPage(api: _GoldenApi(), onAuthenticated: () {}),
    );
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/auth_login.png'),
    );
  });

  testWidgets('golden: onboarding intro', (tester) async {
    // [人工注释][S1-026] Golden 直接渲染正式 OnboardingIntroPage；固定字体/窗口仍复用本文件统一基线。
    final key = await _pumpSurface(
      tester,
      Scaffold(
        body: SafeArea(
          child: OnboardingIntroPage(onStart: () {}, onSkip: () {}),
        ),
      ),
    );
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/onboarding_intro.png'),
    );
  });

  testWidgets('golden: today home', (tester) async {
    final key = await _pumpGoldenToday(tester);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/home_today.png'),
    );
  });

  testWidgets('golden: timeline', (tester) async {
    final api = _GoldenTimelineApi();
    final cache = await _seedGoldenMediaCache(api.authenticatedUserId!);
    final key = await _pumpSurface(
      tester,
      TimelinePage(api: api, mediaCache: cache),
    );
    expect(find.text('时间线'), findsWidgets);
    expect(find.text('第一次产品讨论'), findsOneWidget);
    expect(find.text('周末咖啡店'), findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/timeline.png'),
    );
  });

  testWidgets('golden: people', (tester) async {
    final key = await _pumpSurface(tester, PeoplePage(api: V2TestApi()));
    expect(find.text('重要的人'), findsWidgets);
    expect(find.text('老张'), findsWidgets);
    await expectLater(find.byKey(key), matchesGoldenFile('goldens/people.png'));
  });

  testWidgets('golden: life home', (tester) async {
    final key = await _pumpSurface(tester, LifePage(api: V2TestApi()));
    expect(find.text('我的人生'), findsWidgets);
    expect(find.text('人生经历'), findsOneWidget);
    await expectLater(find.byKey(key), matchesGoldenFile('goldens/life_home.png'));
  });

  testWidgets('golden: family permissions', (tester) async {
    final key = await _pumpSurface(tester, FamilyPage(api: _GoldenFamilyApi()));
    expect(find.text('家庭成员 1'), findsOneWidget);
    expect(find.text('可查看我的记忆'), findsOneWidget);
    expect(find.text('可查看我的照片'), findsOneWidget);
    expect(find.textContaining(_GoldenFamilyApi.memberId), findsNothing);
    await expectLater(find.byKey(key), matchesGoldenFile('goldens/family_permissions.png'));
  });

  testWidgets('golden: empty timeline state', (tester) async {
    final key = await _pumpSurface(
      tester,
      TimelinePage(api: _GoldenEmptyTimelineApi()),
    );
    expect(find.text('还没有时间线记录'), findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/state_empty.png'),
    );
  });

  testWidgets('golden: offline timeline state', (tester) async {
    final key = await _pumpSurface(tester, TimelinePage(api: _GoldenOfflineTimelineApi()));
    expect(find.text('当前离线'), findsOneWidget);
    expect(find.text('重新连接'), findsOneWidget);
    await expectLater(find.byKey(key), matchesGoldenFile('goldens/state_offline.png'));
  });

  testWidgets('golden: Elder memory query', (tester) async {
    final key = await _pumpSurface(
      tester,
      Scaffold(
        body: SafeArea(
          child: MemoryQueryPage(api: _GoldenApi(), elderMode: true),
        ),
      ),
      elderMode: true,
    );
    expect(find.text('我想找东西'), findsOneWidget);
    final submit = find.byKey(const ValueKey('memory-query-submit'));
    expect(tester.getSize(submit).height, greaterThanOrEqualTo(56));
    await expectLater(find.byKey(key), matchesGoldenFile('goldens/elder_memory_query.png'));
  });

  testWidgets('golden: capture and object location', (tester) async {
    final key = await _pumpSurface(
      tester,
      Scaffold(
        body: SafeArea(
          child: CapturePage(
            api: _GoldenApi(),
            offlineQueue: _GoldenQueue(),
          ),
        ),
      ),
    );
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/capture_object.png'),
    );
  });

  testWidgets('golden: unified capture media controls', (tester) async {
    final key = await _pumpSurface(
      tester,
      Scaffold(
        body: SafeArea(
          child: CapturePage(
            api: _GoldenApi(),
            offlineQueue: _GoldenQueue(),
          ),
        ),
      ),
    );

    final voiceStart =
        find.byKey(const ValueKey<String>('capture-voice-start'));
    await tester.ensureVisible(voiceStart);
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey<String>('capture-photo-camera')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey<String>('capture-photo-gallery')),
      findsOneWidget,
    );
    expect(voiceStart, findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/capture_media.png'),
    );
  });

  testWidgets('golden: memory query', (tester) async {
    final key = await _pumpGoldenMemoryQuery(tester);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/memory_query.png'),
    );
  });

  testWidgets(
    'preview: deterministic memory query trust label',
    (tester) async {
      // This preview validates Memory Query trust labeling only. Keep it isolated
      // from AppShell background sync/location lifecycles so the focused CI gate
      // cannot be held open by unrelated shell work.
      final key = await _pumpSurface(
        tester,
        Scaffold(
          body: SafeArea(
            child: MemoryQueryPage(api: _GoldenApi()),
          ),
        ),
      );
      await tester.enterText(
        find.byKey(const ValueKey('memory-query-input')),
        '护照在哪里？',
      );
      await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
      await tester.pumpAndSettle();

      expect(find.text('AI 整理'), findsNothing);
      expect(find.text('明确记录'), findsOneWidget);
      expect(find.textContaining('用户文字记录'), findsOneWidget);
      await expectLater(
        find.byKey(key),
        matchesGoldenFile('/tmp/deterministic_memory_query.png'),
      );
    },
    skip: !_captureDeterministicQueryPreview,
  );

  testWidgets('golden: memory detail', (tester) async {
    final api = _GoldenMemoryDetailApi();
    final cache = await _seedGoldenMediaCache(api.authenticatedUserId!);
    final key = await _pumpSurface(
      tester,
      MemoryDetailPage(
        api: api,
        memoryId: v2MemoryId,
        mediaCache: cache,
      ),
    );
    expect(find.text('第一次产品讨论'), findsWidgets);
    expect(find.text('上海办公室'), findsOneWidget);
    expect(find.textContaining('整块白板'), findsOneWidget);
    expect(find.textContaining(v2MemoryId), findsNothing);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/memory_detail.png'),
    );
  });

  testWidgets('golden: profile and privacy controls', (tester) async {
    // [人工注释][CI-005] Profile 使用确定性的 fake API 返回固定资料/暂停状态，
    // 只稳定异步输入，不复制或重写产品 UI。
    final key = await _pumpGoldenProfile(tester);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/profile_privacy.png'),
    );
  });

  testWidgets('golden: profile privacy paused', (tester) async {
    final key = await _pumpGoldenProfile(
      tester,
      api: _GoldenApi(
        privacyStatus: const {
          'recording_paused': true,
          'paused_until': '2026-09-18T01:30:00+08:00',
        },
      ),
    );

    // Stage 2 adds a second, deliberate pause indicator for the native producer:
    // one banner is the authoritative server privacy state, the other proves native
    // location production has also converged to paused.
    expect(find.text('自动采集已暂停'), findsNWidgets(2));
    expect(find.textContaining('2026-09-18T01:30:00+08:00'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '恢复记录'), findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/profile_privacy_paused.png'),
    );
  });

  testWidgets('privacy error stays unknown and never renders active success', (
    tester,
  ) async {
    final key = await _pumpGoldenProfile(
      tester,
      api: _GoldenApi(privacyError: ApiException(503, '服务端状态读取失败')),
    );

    expect(find.text('无法确认当前隐私状态'), findsOneWidget);
    expect(find.text('服务端状态读取失败'), findsOneWidget);
    expect(find.text('当前没有暂停自动采集'), findsNothing);
    expect(find.text('自动采集已暂停'), findsNothing);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/profile_privacy_error.png'),
    );
  });
  testWidgets('golden: place detail loaded', (tester) async {
    // [人工注释][S2-013] 固定一条 finalized + 一条 mutable Visit，并保留分页入口，
    // 视觉基线专门覆盖“可信状态标签 + 地点概况 + 加载更多”的产品展示边界。
    final key = await _pumpSurface(
      tester,
      PlaceDetailPage(
        api: _GoldenPlaceDetailApi(),
        placeId: 'place-golden-1',
      ),
    );
    expect(find.text('常去的咖啡店'), findsOneWidget);
    expect(find.text('已稳定的到访'), findsOneWidget);
    expect(find.text('仍在更新的到访'), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, '加载更多'), findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/place_detail_loaded.png'),
    );
  });


  testWidgets('golden: V2 person detail', (tester) async {
    final key = await _pumpSurface(
      tester,
      PersonDetailPage(api: V2TestApi(), personId: v2PersonId),
    );
    expect(find.text('认识时长'), findsOneWidget);
    expect(find.textContaining('至少 577 天'), findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/v2_person_detail.png'),
    );
  });

  testWidgets('golden: V2 graph neighborhood', (tester) async {
    final key = await _pumpSurface(
      tester,
      GraphNeighborhoodPage(
        api: V2TestApi(),
        kind: 'PERSON',
        entityId: v2PersonId,
        title: '老张',
      ),
    );
    expect(find.text('相关的人和事'), findsWidgets);
    expect(find.textContaining('小李'), findsWidgets);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/v2_graph_neighborhood.png'),
    );
  });

  testWidgets('golden: V2 life event detail', (tester) async {
    final key = await _pumpSurface(
      tester,
      LifeEventDetailPage(api: V2TestApi(), eventId: v2EventId),
    );
    expect(find.text('相关记录'), findsOneWidget);
    expect(find.text('AI 整理'), findsNothing);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/v2_life_event_detail.png'),
    );
  });

  testWidgets('golden: V2 long-term reasoning answered', (tester) async {
    final key = await _pumpSurface(
      tester,
      LifeStageDetailPage(api: V2TestApi(), stageId: v2StageId),
    );
    await tester.enterText(
      find.byType(TextField).last,
      '这个阶段发生了什么？',
    );
    final generate = find.text('生成回顾');
    await tester.ensureVisible(generate);
    await tester.pumpAndSettle();
    await tester.tap(generate);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('AI 整理'));
    await tester.pumpAndSettle();
    expect(find.textContaining('持续围绕产品开发'), findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/v2_reasoning_answered.png'),
    );
  });

  testWidgets('golden: V2 annual memoir ready', (tester) async {
    final api = V2TestApi();
    final cache = await _seedGoldenMediaCache(v2OwnerId);
    final key = await _pumpSurface(
      tester,
      MemoirsPage(api: api, mediaCache: cache),
    );
    await tester.enterText(find.byType(TextField).first, '2025');
    final annual = find.text('开始回看');
    await tester.ensureVisible(annual);
    await tester.pumpAndSettle();
    await tester.tap(annual);
    await tester.pumpAndSettle();
    final storyHero = find.byKey(const ValueKey('annual-story-hero'));
    await tester.ensureVisible(storyHero);
    await tester.pumpAndSettle();
    expect(storyHero, findsOneWidget);
    expect(find.text('这一年的故事'), findsOneWidget);
    expect(find.textContaining('新的产品阶段'), findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/v2_annual_memoir_ready.png'),
    );
  });

  testWidgets('golden: V2 life memoir chapter ready', (tester) async {
    final key = await _pumpSurface(
      tester,
      MemoirsPage(api: V2TestApi()),
    );
    final stage = find.text('产品创业阶段');
    await tester.scrollUntilVisible(
      stage,
      280,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();
    await tester.tap(stage);
    await tester.pumpAndSettle();
    final generate = find.text('生成这个阶段的故事');
    await tester.ensureVisible(generate);
    await tester.tap(generate);
    await tester.pumpAndSettle();
    final narrative = find.textContaining('这一阶段以产品开发为主线');
    await tester.ensureVisible(narrative);
    await tester.pumpAndSettle();
    expect(narrative, findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/v2_life_memoir_chapter.png'),
    );
  });

  testWidgets('golden: V2 AI unavailable fail closed', (tester) async {
    final key = await _pumpSurface(
      tester,
      LifeStageDetailPage(
        api: V2TestApi(reasoningStatus: 'PROVIDER_FAILED'),
        stageId: v2StageId,
      ),
    );
    await tester.enterText(
      find.byType(TextField).last,
      '这个阶段发生了什么？',
    );
    final generate = find.text('生成回顾');
    await tester.ensureVisible(generate);
    await tester.pumpAndSettle();
    await tester.tap(generate);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('暂时无法整理'));
    await tester.pumpAndSettle();
    expect(find.textContaining('持续围绕产品开发'), findsNothing);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/v2_ai_unavailable.png'),
    );
  });


  testWidgets('golden: design authority Today map photo', (tester) async {
    final key = await _pumpGoldenToday(
      tester,
      mapAccepted: true,
    );

    expect(find.byKey(const ValueKey('amap-real-surface')), findsOneWidget);
    expect(find.byKey(const ValueKey('today-photo-$v2MemoryId')), findsOneWidget);
    expect(find.text('晨光里的白板'), findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/design_authority_today.png'),
    );
  });

  testWidgets('golden: design authority Timeline photo first', (tester) async {
    final api = _GoldenTimelineApi();
    final cache = await _seedGoldenMediaCache(api.authenticatedUserId!);
    final key = await _pumpSurface(
      tester,
      TimelinePage(api: api, mediaCache: cache),
    );

    expect(find.text('第一次产品讨论'), findsOneWidget);
    expect(find.byKey(const ValueKey('timeline-photo-$v2MemoryId')), findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/design_authority_timeline.png'),
    );
  });

  testWidgets('golden: design authority Memory Detail photo map',
      (tester) async {
    final api = _GoldenMemoryDetailApi();
    final cache = await _seedGoldenMediaCache(api.authenticatedUserId!);
    final key = await _pumpSurface(
      tester,
      MemoryDetailPage(
        api: api,
        memoryId: v2MemoryId,
        mediaCache: cache,
        amapPrivacyConsent: _GoldenAmapConsent(true),
      ),
    );

    expect(find.text('第一次产品讨论'), findsWidgets);
    expect(find.byKey(const ValueKey('amap-place-real-surface')), findsOneWidget);
    expect(find.text('照片'), findsWidgets);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/design_authority_memory_detail.png'),
    );
  });

  testWidgets('golden: design authority Family shared content',
      (tester) async {
    final api = _GoldenFamilyApi();
    final mediaKey =
        '${_GoldenFamilyApi.memberId.toLowerCase()}_${v2MediaId.toLowerCase()}';
    final cache = await _seedGoldenMediaCache(
      api.authenticatedUserId!,
      mediaId: mediaKey,
    );
    final key = await _pumpSurface(
      tester,
      FamilyPage(
        api: api,
        mediaCache: cache,
        amapPrivacyConsent: _GoldenAmapConsent(true),
      ),
    );

    await tester.tap(
      find.byKey(
        const ValueKey(
          'family-shared-open-${_GoldenFamilyApi.memberId}',
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('family-read-photos')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('family-read-location')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('family-photo-grid')), findsOneWidget);
    expect(find.byKey(const ValueKey('amap-place-real-surface')), findsOneWidget);
    final map = find.byKey(const ValueKey('amap-place-real-surface'));
    await tester.scrollUntilVisible(
      map,
      180,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/design_authority_family.png'),
    );
  });

  testWidgets('golden: design authority Memory Query evidence map',
      (tester) async {
    final api = _GoldenHistoricalQueryApi();
    final key = await _pumpSurface(
      tester,
      Scaffold(
        body: SafeArea(
          child: MemoryQueryPage(
            api: api,
            amapPrivacyConsent: _GoldenAmapConsent(true),
          ),
        ),
      ),
    );

    await tester.enterText(
      find.byKey(const ValueKey('memory-query-input')),
      '我 9 月 20 日去了哪里？',
    );
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('memory-query-day-map')), findsOneWidget);
    expect(find.byKey(const ValueKey('amap-real-surface')), findsOneWidget);
    expect(find.text('为什么这么回答'), findsOneWidget);
    final map = find.byKey(const ValueKey('amap-real-surface'));
    await tester.ensureVisible(map);
    await tester.pumpAndSettle();
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/design_authority_memory_query.png'),
    );
  });

  testWidgets('golden: design authority Unified Capture', (tester) async {
    final key = await _pumpSurface(
      tester,
      Scaffold(
        body: SafeArea(
          child: CapturePage(
            api: _GoldenApi(),
            offlineQueue: _GoldenQueue(),
          ),
        ),
      ),
    );

    expect(
      find.byKey(const ValueKey<String>('capture-photo-camera')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey<String>('capture-photo-gallery')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey<String>('capture-voice-start')),
      findsOneWidget,
    );
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/design_authority_capture.png'),
    );
  });

  testWidgets('golden: design authority Annual Summary photo story',
      (tester) async {
    final api = V2TestApi();
    final cache = await _seedGoldenMediaCache(v2OwnerId);
    final key = await _pumpSurface(
      tester,
      MemoirsPage(api: api, mediaCache: cache),
    );

    await tester.enterText(find.byType(TextField).first, '2025');
    final start = find.text('开始回看');
    await tester.ensureVisible(start);
    await tester.tap(start);
    await tester.pumpAndSettle();

    final photo = find.byKey(const ValueKey('annual-photo-$v2MediaId'));
    expect(photo, findsOneWidget);
    await tester.ensureVisible(photo);
    await tester.pumpAndSettle();
    expect(find.text('这一年的照片'), findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/design_authority_summary.png'),
    );
  });

  testWidgets('golden: design authority Profile privacy', (tester) async {
    final key = await _pumpGoldenProfile(
      tester,
      mapAccepted: true,
    );

    final amapControl = find.text('高德地图服务');
    await tester.scrollUntilVisible(
      amapControl,
      180,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();

    expect(find.text('隐私与记录控制'), findsOneWidget);
    expect(find.byKey(const ValueKey('amap-privacy-revoke')), findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/design_authority_profile.png'),
    );
  });

}
