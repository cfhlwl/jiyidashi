import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/amap_privacy_consent.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/place_detail_page.dart';
import 'package:jiyidashi/stage1_app.dart';

const _timelinePlaceId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

class _PlaceConsent implements AmapPrivacyConsentAuthority {
  _PlaceConsent(this.accepted);

  bool accepted;

  @override
  Future<void> accept() async => accepted = true;

  @override
  Future<bool> readAccepted() async => accepted;

  @override
  Future<void> revoke() async => accepted = false;
}

class _PlaceApi extends JiYiApiClient {
  _PlaceApi({
    this.detail,
    this.detailError,
    this.places = const [],
    this.pendingDetail,
    this.nextDetail,
  }) : super(baseUrl: 'http://place-detail.invalid/v1') {
    accessToken = 'token';
    authenticatedUserId = 'owner';
  }

  final Map<String, dynamic>? detail;
  final Object? detailError;
  final List<Map<String, dynamic>> places;
  final Completer<Map<String, dynamic>>? pendingDetail;
  final Map<String, dynamic>? nextDetail;
  int detailCalls = 0;
  String? lastPlaceId;

  @override
  Future<List<Map<String, dynamic>>> listPlaces({int limit = 100}) async => places;

  @override
  Future<Map<String, dynamic>> getTimelineEvents({
    int limit = 30,
    String? cursor,
    String? day,
  }) async {
    if (places.isEmpty) {
      return {
        'timezone': 'Asia/Shanghai',
        'day': null,
        'items': const <Map<String, dynamic>>[],
        'next_cursor': null,
      };
    }
    final place = places.first;
    return {
      'timezone': 'Asia/Shanghai',
      'day': null,
      'items': [
        {
          'kind': 'VISIT',
          'id': '11111111-1111-4111-8111-111111111111',
          'occurred_at': '2026-09-20T08:00:00Z',
          'ended_at': '2026-09-20T09:00:00Z',
          'place_id': _timelinePlaceId,
          'place_name': place['name'],
          'memory_type': null,
          'title': null,
          'content': null,
          'is_confirmed': null,
          'confidence': 0.92,
          'visit_finalized': true,
        },
      ],
      'next_cursor': null,
    };
  }

  @override
  Future<Map<String, dynamic>> getPlaceDetail(
    String placeId, {
    int limit = 50,
    String? cursor,
  }) async {
    detailCalls += 1;
    lastPlaceId = placeId;
    if (pendingDetail != null) return pendingDetail!.future;
    if (detailError != null) throw detailError!;
    if (cursor != null) {
      return nextDetail ??
          {
            'place': detail!['place'],
            'visits': [_visit(id: 'visit-2', finalized: false)],
            'next_cursor': null,
          };
    }
    return detail!;
  }
}

Map<String, dynamic> _visit({
  String id = 'visit-1',
  bool finalized = true,
}) {
  return {
    'id': id,
    'arrived_at': '2026-09-20T08:00:00Z',
    'left_at': finalized ? '2026-09-20T09:00:00Z' : null,
    'duration_seconds': finalized ? 3600 : null,
    'confidence': 0.92,
    'source': 'GPS',
    'finalized_at': finalized ? '2026-09-20T10:00:00Z' : null,
    'visit_finalized': finalized,
  };
}

Map<String, dynamic> _place({
  List<Map<String, dynamic>> visits = const [],
  Object? cursor,
  String placeId = _timelinePlaceId,
  String name = '家',
  String nameSource = 'USER',
  double? latitude,
  double? longitude,
}) {
  return {
    'place': {
      'id': placeId,
      'name': name,
      'name_source': nameSource,
      'address': '测试地址',
      'category': 'HOME',
      'latitude': latitude,
      'longitude': longitude,
      'visit_count': 2,
      'first_visited_at': '2026-09-18T08:00:00Z',
      'last_visited_at': '2026-09-20T08:00:00Z',
    },
    'visits': visits,
    'next_cursor': cursor,
  };
}

void main() {
  testWidgets('PlaceDetailPage exposes explicit loading state', (tester) async {
    final completer = Completer<Map<String, dynamic>>();
    final api = _PlaceApi(pendingDetail: completer);
    await tester.pumpWidget(
      MaterialApp(home: PlaceDetailPage(api: api, placeId: _timelinePlaceId)),
    );
    expect(find.text('正在读取地点详情…'), findsOneWidget);
  });

  testWidgets('PlaceDetailPage exposes error and retry state', (tester) async {
    final api = _PlaceApi(detailError: ApiException(404, 'PLACE_NOT_FOUND'));
    await tester.pumpWidget(
      MaterialApp(home: PlaceDetailPage(api: api, placeId: _timelinePlaceId)),
    );
    await tester.pumpAndSettle();
    expect(find.text('无法读取地点详情'), findsOneWidget);
    expect(find.text('PLACE_NOT_FOUND'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '重试'), findsOneWidget);
  });

  testWidgets('PlaceDetailPage exposes an explicit offline state', (tester) async {
    final api = _PlaceApi(detailError: TransportException('网络连接失败'));
    await tester.pumpWidget(
      MaterialApp(home: PlaceDetailPage(api: api, placeId: _timelinePlaceId)),
    );
    await tester.pumpAndSettle();

    expect(find.text('当前离线'), findsOneWidget);
    expect(find.text('网络连接失败'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '重试'), findsOneWidget);
  });

  testWidgets('PlaceDetailPage exposes empty retained-visit state', (tester) async {
    final api = _PlaceApi(detail: _place());
    await tester.pumpWidget(
      MaterialApp(home: PlaceDetailPage(api: api, placeId: _timelinePlaceId)),
    );
    await tester.pumpAndSettle();
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('place-summary-card')),
        matching: find.text('家'),
      ),
      findsOneWidget,
    );
    expect(find.text('还没有到访记录'), findsOneWidget);
  });

  testWidgets('PlaceDetailPage keeps no-coordinate places truthful', (tester) async {
    final api = _PlaceApi(
      detail: _place(name: '', nameSource: 'UNNAMED'),
    );
    await tester.pumpWidget(
      MaterialApp(home: PlaceDetailPage(api: api, placeId: _timelinePlaceId)),
    );
    await tester.pumpAndSettle();

    expect(find.text('未知地点'), findsWidgets);
    expect(find.byKey(const ValueKey('place-map-no-coordinate-state')), findsOneWidget);
    expect(find.byKey(const ValueKey('place-map-surface')), findsNothing);
    expect(find.byKey(const ValueKey('amap-place-real-surface')), findsNothing);
  });

  testWidgets('PlaceDetailPage gates real map behind privacy consent', (tester) async {
    final consent = _PlaceConsent(false);
    final api = _PlaceApi(detail: _place(latitude: 31.2243, longitude: 121.4768));
    await tester.pumpWidget(
      MaterialApp(
        home: PlaceDetailPage(
          api: api,
          placeId: _timelinePlaceId,
          amapPrivacyConsent: consent,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('amap-place-privacy-blocked')), findsOneWidget);
    expect(find.byKey(const ValueKey('place-amap-privacy-accept')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('place-amap-privacy-accept')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('amap-privacy-confirm')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('amap-privacy-confirm')));
    await tester.pumpAndSettle();

    expect(consent.accepted, isTrue);
    expect(find.byKey(const ValueKey('amap-place-privacy-blocked')), findsNothing);
    expect(find.byKey(const ValueKey('amap-place-key-unavailable')), findsOneWidget);
    expect(find.byKey(const ValueKey('amap-place-real-surface')), findsNothing);
  });

  testWidgets('PlaceDetailPage rejects a returned place identity mismatch', (tester) async {
    final api = _PlaceApi(detail: _place(placeId: 'another-place'));
    await tester.pumpWidget(
      MaterialApp(home: PlaceDetailPage(api: api, placeId: _timelinePlaceId)),
    );
    await tester.pumpAndSettle();

    expect(find.text('无法读取地点详情'), findsOneWidget);
    expect(find.text('家'), findsNothing);
  });

  testWidgets('PlaceDetailPage drops stale response after owner changes', (tester) async {
    final response = Completer<Map<String, dynamic>>();
    final api = _PlaceApi(pendingDetail: response);
    await tester.pumpWidget(
      MaterialApp(home: PlaceDetailPage(api: api, placeId: _timelinePlaceId)),
    );
    expect(find.text('正在读取地点详情…'), findsOneWidget);

    api.authenticatedUserId = 'different-owner';
    response.complete(_place());
    await tester.pumpAndSettle();

    expect(find.text('正在读取地点详情…'), findsOneWidget);
    expect(find.text('家'), findsNothing);
  });

  testWidgets('PlaceDetailPage remains usable on small screens with large text',
      (tester) async {
    final api = _PlaceApi(detail: _place(visits: [_visit()]));
    tester.view.physicalSize = const Size(320, 568);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(
          size: Size(320, 568),
          textScaler: TextScaler.linear(2),
        ),
        child: MaterialApp(
          home: PlaceDetailPage(api: api, placeId: _timelinePlaceId),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.bySemanticsLabel('返回'), findsOneWidget);
    expect(find.text('地点详情'), findsOneWidget);
  });

  testWidgets('PlaceDetailPage distinguishes finalized and mutable visits and paginates', (tester) async {
    final api = _PlaceApi(
      detail: _place(
        visits: [_visit()],
        cursor: 'next-page',
      ),
    );
    await tester.pumpWidget(
      MaterialApp(home: PlaceDetailPage(api: api, placeId: _timelinePlaceId)),
    );
    await tester.pumpAndSettle();
    expect(find.text('已稳定的到访'), findsOneWidget);
    await tester.ensureVisible(find.byKey(const ValueKey('place-load-more')));
    await tester.tap(find.widgetWithText(OutlinedButton, '加载更多'));
    await tester.pumpAndSettle();
    expect(find.text('仍在更新的到访'), findsOneWidget);
    expect(api.detailCalls, 2);
  });

  testWidgets(
    'PlaceDetailPage rejects non-bool finalized instead of rendering mutable fact',
    (tester) async {
      final malformed = _visit()..['visit_finalized'] = 'true';
      final api = _PlaceApi(detail: _place(visits: [malformed]));
      await tester.pumpWidget(
        MaterialApp(home: PlaceDetailPage(api: api, placeId: _timelinePlaceId)),
      );
      await tester.pumpAndSettle();

      expect(find.text('无法读取地点详情'), findsOneWidget);
      expect(find.text('仍在更新的到访'), findsNothing);
      expect(find.text('已稳定的到访'), findsNothing);
    },
  );

  testWidgets(
    'PlaceDetailPage rejects malformed next cursor atomically without appending visits',
    (tester) async {
      final initial = _place(visits: [_visit()], cursor: 'next-page');
      final malformedNext = _place(
        visits: [_visit(id: 'visit-2', finalized: false)],
        cursor: 123,
      );
      final api = _PlaceApi(detail: initial, nextDetail: malformedNext);

      await tester.pumpWidget(
        MaterialApp(home: PlaceDetailPage(api: api, placeId: _timelinePlaceId)),
      );
      await tester.pumpAndSettle();
      expect(find.text('已稳定的到访'), findsOneWidget);

      await tester.ensureVisible(find.byKey(const ValueKey('place-load-more')));
      await tester.tap(find.widgetWithText(OutlinedButton, '加载更多'));
      await tester.pumpAndSettle();

      expect(find.text('部分到访记录加载失败'), findsOneWidget);
      expect(find.text('仍在更新的到访'), findsNothing);
      expect(find.textContaining('visit-2'), findsNothing);
    },
  );

  testWidgets('Timeline place entry opens PlaceDetailPage', (tester) async {
    final api = _PlaceApi(
      places: const [
        {'id': 'place-1', 'name': '家', 'address': '测试地址'}
      ],
      detail: _place(),
    );
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: TimelinePage(api: api))));
    await tester.pumpAndSettle();
    final placeChip = find.widgetWithText(Chip, '家');
    expect(placeChip, findsOneWidget);
    await tester.tap(placeChip);
    await tester.pumpAndSettle();
    expect(api.lastPlaceId, _timelinePlaceId);
    expect(find.text('地点详情'), findsOneWidget);
    expect(find.text('还没有到访记录'), findsOneWidget);
  });
}
