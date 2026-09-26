import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/today_footprint_page.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';

class _TodayApi extends JiYiApiClient {
  _TodayApi({required this.response, this.error})
      : super(baseUrl: 'https://example.test/v1') {
    accessToken = 'token';
    authenticatedUserId = '11111111-1111-4111-8111-111111111111';
  }

  final Map<String, dynamic> response;
  final Object? error;

  @override
  Future<Map<String, dynamic>> getTodayFootprint() async {
    final failure = error;
    if (failure != null) throw failure;
    return response;
  }
}

Future<void> _pump(
  WidgetTester tester,
  JiYiApiClient api, {
  bool elderMode = false,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: JiYiTheme.light(elderMode: elderMode),
      home: Scaffold(body: TodayPage(api: api, elderMode: elderMode)),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('today footprint renders server-local order and visit state', (tester) async {
    await _pump(
      tester,
      _TodayApi(
        response: {
          'timezone': 'Asia/Shanghai',
          'day': '2026-09-20',
          'visits': [
            {
              'id': '11111111-1111-4111-8111-111111111111',
              'place_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
              'place_name': '家',
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
              'arrived_at': '2026-09-20T00:35:00Z',
              'left_at': null,
              'arrived_at_local': '2026-09-20T08:35:00+08:00',
              'left_at_local': null,
              'confidence': 0.88,
              'visit_source': 'LOCATION_CLUSTER',
              'visit_finalized': false,
            },
          ],
        },
      ),
    );

    expect(find.byKey(const ValueKey('today-footprint-loaded')), findsOneWidget);
    expect(find.text('2026-09-20 · Asia/Shanghai · 2 条地点记录'), findsOneWidget);
    expect(find.text('家'), findsOneWidget);
    expect(find.text('07:10 - 08:00'), findsOneWidget);
    expect(find.text('已形成足迹 · LOCATION_CLUSTER'), findsOneWidget);
    expect(find.text('公司'), findsOneWidget);
    expect(find.text('08:35 起'), findsOneWidget);
    expect(find.text('进行中 · LOCATION_CLUSTER'), findsOneWidget);
  });

  testWidgets('today footprint has explicit empty state', (tester) async {
    await _pump(
      tester,
      _TodayApi(
        response: const {
          'timezone': 'Asia/Shanghai',
          'day': '2026-09-20',
          'visits': <Map<String, dynamic>>[],
        },
      ),
    );

    expect(find.byKey(const ValueKey('today-footprint-empty')), findsOneWidget);
    expect(find.text('今天还没有形成足迹'), findsOneWidget);
  });

  testWidgets('today footprint fails visibly and offers retry', (tester) async {
    await _pump(
      tester,
      _TodayApi(
        response: const {},
        error: ApiException(503, 'temporary failure'),
      ),
    );

    expect(find.byKey(const ValueKey('today-footprint-error')), findsOneWidget);
    expect(find.text('无法读取今日足迹'), findsOneWidget);
    expect(find.byKey(const ValueKey('today-footprint-retry')), findsOneWidget);
  });

  testWidgets('Elder Today shows simplified trusted rows without implementation labels', (tester) async {
    await _pump(
      tester,
      _TodayApi(
        response: {
          'timezone': 'Asia/Shanghai',
          'day': '2026-09-20',
          'visits': [
            {
              'id': 'first',
              'place_id': 'p1',
              'place_name': '家',
              'arrived_at': '2026-09-19T23:10:00Z',
              'left_at': '2026-09-20T00:00:00Z',
              'arrived_at_local': '2026-09-20T07:10:00+08:00',
              'left_at_local': '2026-09-20T08:00:00+08:00',
              'confidence': 0.94,
              'visit_source': 'LOCATION_CLUSTER',
              'visit_finalized': true,
            },
            {
              'id': 'second',
              'place_id': 'p2',
              'place_name': '公司',
              'arrived_at': '2026-09-20T00:35:00Z',
              'left_at': null,
              'arrived_at_local': '2026-09-20T08:35:00+08:00',
              'left_at_local': null,
              'confidence': 0.88,
              'visit_source': 'LOCATION_CLUSTER',
              'visit_finalized': false,
            },
          ],
        },
      ),
      elderMode: true,
    );

    expect(find.text('今天去了哪里'), findsWidgets);
    expect(find.text('家'), findsOneWidget);
    expect(find.text('07:10 - 08:00'), findsOneWidget);
    expect(find.text('公司'), findsOneWidget);
    expect(find.text('08:35 起'), findsOneWidget);
    expect(find.textContaining('LOCATION_CLUSTER'), findsNothing);
    expect(find.textContaining('你现在就在'), findsNothing);
    expect(find.textContaining('当前位置是'), findsNothing);

    final homeY = tester.getTopLeft(find.text('家')).dy;
    final workY = tester.getTopLeft(find.text('公司')).dy;
    expect(homeY, lessThan(workY));
  });

  testWidgets('Elder empty footprint is truthful and never claims no outing', (tester) async {
    await _pump(
      tester,
      _TodayApi(
        response: const {
          'timezone': 'Asia/Shanghai',
          'day': '2026-09-20',
          'visits': <Map<String, dynamic>>[],
        },
      ),
      elderMode: true,
    );

    expect(find.text('今天还没有形成足迹'), findsWidgets);
    expect(find.textContaining('不会用当前位置猜测'), findsWidgets);
    expect(find.textContaining('今天没有出门'), findsNothing);
    expect(find.textContaining('一直在家'), findsNothing);
    expect(find.textContaining('没有去任何地方'), findsNothing);
  });

  testWidgets('late account A footprint cannot populate after switch to B', (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    final api = _PendingTodayApi(pending);
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(elderMode: true),
        home: Scaffold(body: TodayPage(api: api, elderMode: true)),
      ),
    );
    await tester.pump();

    api.logout();
    api.accessToken = 'token-b';
    api.authenticatedUserId = 'owner-b';
    pending.complete({
      'timezone': 'Asia/Shanghai',
      'day': '2026-09-20',
      'visits': [
        {
          'id': 'old-a',
          'place_id': 'p-a',
          'place_name': 'A 的旧地点',
          'arrived_at': '2026-09-20T00:00:00Z',
          'left_at': null,
          'arrived_at_local': '2026-09-20T08:00:00+08:00',
          'left_at_local': null,
          'confidence': 1.0,
          'visit_source': 'LOCATION_CLUSTER',
          'visit_finalized': false,
        },
      ],
    });
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('A 的旧地点'), findsNothing);
  });

  testWidgets('disposing Today page blocks late footprint publication', (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    final api = _PendingTodayApi(pending);
    await tester.pumpWidget(
      MaterialApp(home: Scaffold(body: TodayPage(api: api, elderMode: true))),
    );
    await tester.pump();

    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: Text('replacement'))));
    pending.complete(const {
      'timezone': 'Asia/Shanghai',
      'day': '2026-09-20',
      'visits': <Map<String, dynamic>>[],
    });
    await tester.pumpAndSettle();

    expect(find.text('replacement'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('retry succeeds after initial Today footprint error', (tester) async {
    final api = _RetryTodayApi();
    await tester.pumpWidget(
      MaterialApp(home: Scaffold(body: TodayPage(api: api, elderMode: true))),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('today-footprint-error')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('today-footprint-retry')));
    await tester.pumpAndSettle();
    expect(find.text('重试成功地点'), findsOneWidget);
    expect(api.calls, 2);
  });

  testWidgets('Elder Today has no location producer or mutation side effect', (tester) async {
    final api = _SideEffectTodayApi();
    await _pump(tester, api, elderMode: true);
    expect(api.reads, 1);
    expect(api.locationWrites, 0);
    expect(api.privacyWrites, 0);
    expect(api.placeWrites, 0);
  });

}


class _PendingTodayApi extends JiYiApiClient {
  _PendingTodayApi(this.pending) : super(baseUrl: 'https://pending.invalid/v1') {
    accessToken = 'token-a';
    authenticatedUserId = 'owner-a';
  }

  final Completer<Map<String, dynamic>> pending;

  @override
  Future<Map<String, dynamic>> getTodayFootprint() => pending.future;
}

class _RetryTodayApi extends JiYiApiClient {
  _RetryTodayApi() : super(baseUrl: 'https://retry.invalid/v1') {
    accessToken = 'token';
    authenticatedUserId = 'owner';
  }

  int calls = 0;

  @override
  Future<Map<String, dynamic>> getTodayFootprint() async {
    calls += 1;
    if (calls == 1) throw ApiException(503, 'temporary');
    return {
      'timezone': 'Asia/Shanghai',
      'day': '2026-09-20',
      'visits': [
        {
          'id': 'retry',
          'place_id': 'p',
          'place_name': '重试成功地点',
          'arrived_at': '2026-09-20T01:00:00Z',
          'left_at': null,
          'arrived_at_local': '2026-09-20T09:00:00+08:00',
          'left_at_local': null,
          'confidence': 1.0,
          'visit_source': 'LOCATION_CLUSTER',
          'visit_finalized': false,
        },
      ],
    };
  }
}

class _SideEffectTodayApi extends JiYiApiClient {
  _SideEffectTodayApi() : super(baseUrl: 'https://side.invalid/v1') {
    accessToken = 'token';
    authenticatedUserId = 'owner';
  }

  int reads = 0;
  int locationWrites = 0;
  int privacyWrites = 0;
  int placeWrites = 0;

  @override
  Future<Map<String, dynamic>> getTodayFootprint() async {
    reads += 1;
    return const {
      'timezone': 'Asia/Shanghai',
      'day': '2026-09-20',
      'visits': <Map<String, dynamic>>[],
    };
  }

  @override
  Future<LocationBatchResult> uploadLocationBatch(List<LocationUploadPoint> points) async {
    locationWrites += 1;
    throw StateError('Today read must not upload location');
  }

  @override
  Future<Map<String, dynamic>> pauseMemory(int minutes) async {
    privacyWrites += 1;
    throw StateError('Today read must not mutate privacy');
  }

  Future<Map<String, dynamic>> createPlaceForTest() async {
    placeWrites += 1;
    throw StateError('Today read must not mutate Place');
  }
}
