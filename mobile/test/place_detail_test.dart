import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/place_detail_page.dart';
import 'package:jiyidashi/stage1_app.dart';

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

  @override
  Future<List<Map<String, dynamic>>> listPlaces({int limit = 100}) async => places;

  @override
  Future<Map<String, dynamic>> getPlaceDetail(
    String placeId, {
    int limit = 50,
    String? cursor,
  }) async {
    detailCalls += 1;
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
}) {
  return {
    'place': {
      'id': 'place-1',
      'name': '家',
      'name_source': 'USER',
      'address': '测试地址',
      'category': 'HOME',
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
      MaterialApp(home: PlaceDetailPage(api: api, placeId: 'place-1')),
    );
    expect(find.text('正在读取地点详情…'), findsOneWidget);
  });

  testWidgets('PlaceDetailPage exposes error and retry state', (tester) async {
    final api = _PlaceApi(detailError: ApiException(404, 'PLACE_NOT_FOUND'));
    await tester.pumpWidget(
      MaterialApp(home: PlaceDetailPage(api: api, placeId: 'place-1')),
    );
    await tester.pumpAndSettle();
    expect(find.text('无法读取地点详情'), findsOneWidget);
    expect(find.text('PLACE_NOT_FOUND'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '重试'), findsOneWidget);
  });

  testWidgets('PlaceDetailPage exposes empty retained-visit state', (tester) async {
    final api = _PlaceApi(detail: _place());
    await tester.pumpWidget(
      MaterialApp(home: PlaceDetailPage(api: api, placeId: 'place-1')),
    );
    await tester.pumpAndSettle();
    expect(find.text('家'), findsOneWidget);
    expect(find.text('还没有到访记录'), findsOneWidget);
  });

  testWidgets('PlaceDetailPage distinguishes finalized and mutable visits and paginates', (tester) async {
    final api = _PlaceApi(
      detail: _place(
        visits: [_visit()],
        cursor: 'next-page',
      ),
    );
    await tester.pumpWidget(
      MaterialApp(home: PlaceDetailPage(api: api, placeId: 'place-1')),
    );
    await tester.pumpAndSettle();
    expect(find.text('已稳定的到访'), findsOneWidget);
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
        MaterialApp(home: PlaceDetailPage(api: api, placeId: 'place-1')),
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
        MaterialApp(home: PlaceDetailPage(api: api, placeId: 'place-1')),
      );
      await tester.pumpAndSettle();
      expect(find.text('已稳定的到访'), findsOneWidget);

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
    expect(find.text('地点'), findsOneWidget);
    await tester.tap(find.text('家'));
    await tester.pumpAndSettle();
    expect(find.text('地点详情'), findsOneWidget);
    expect(find.text('还没有到访记录'), findsOneWidget);
  });
}
