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

Future<void> _pump(WidgetTester tester, JiYiApiClient api) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: JiYiTheme.light(),
      home: Scaffold(body: TodayPage(api: api)),
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
}
