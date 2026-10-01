import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/stage1_app.dart';

Map<String, dynamic> footprintResult({
  String placeName = '万达广场',
}) =>
    <String, dynamic>{
      'answer': '2026-09-25 的可靠足迹：\n18:16–19:05  $placeName',
      'can_answer': true,
      'certainty': 'confirmed',
      'reason': null,
      'intent': 'DATE_FOOTPRINT_QUERY',
      'evidence': <Map<String, dynamic>>[],
      'memory_ids': <String>[],
      'day_footprint': <String, dynamic>{
        'timezone': 'Asia/Shanghai',
        'day': '2026-09-25',
        'empty': false,
        'visits': <Map<String, dynamic>>[
          <String, dynamic>{
            'id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'place_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            'place_name': placeName,
            'arrived_at': '2026-09-25T10:16:00Z',
            'left_at': '2026-09-25T11:05:00Z',
            'arrived_at_local': '2026-09-25T18:16:00+08:00',
            'left_at_local': '2026-09-25T19:05:00+08:00',
            'confidence': 0.95,
            'visit_source': 'LOCATION_CLUSTER',
            'visit_finalized': true,
          },
        ],
      },
    };

class _HistoricalQueryApi extends JiYiApiClient {
  _HistoricalQueryApi({
    this.pending,
    Map<String, dynamic>? immediate,
  })  : immediate = immediate ?? footprintResult(),
        super(baseUrl: 'https://example.test/v1') {
    authenticatedUserId = ownerA;
  }

  static const ownerA = '11111111-1111-4111-8111-111111111111';
  static const ownerB = '22222222-2222-4222-8222-222222222222';

  final Completer<Map<String, dynamic>>? pending;
  final Map<String, dynamic> immediate;

  @override
  Future<Map<String, dynamic>> queryMemory(String question) async =>
      pending?.future ?? immediate;
}

Future<void> submitHistoricalQuery(
  WidgetTester tester,
  _HistoricalQueryApi api,
) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(body: MemoryQueryPage(api: api)),
    ),
  );
  await tester.enterText(find.byType(TextField).first, '我25号去哪了？');
  await tester.tap(find.text('从我的记录里找'));
  await tester.pump();
}

void main() {
  testWidgets('structured day footprint renders without evidence warning or enum',
      (tester) async {
    final api = _HistoricalQueryApi();

    await submitHistoricalQuery(tester, api);
    await tester.pumpAndSettle();

    expect(find.textContaining('万达广场'), findsWidgets);
    expect(find.text('18:16 - 19:05'), findsOneWidget);
    expect(find.text('按日期看足迹'), findsOneWidget);
    expect(find.text('DATE_FOOTPRINT_QUERY'), findsNothing);
    expect(find.text('没有可展示的参考记录'), findsNothing);
  });

  testWidgets('late owner A day footprint cannot repopulate owner B query UI',
      (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    final api = _HistoricalQueryApi(pending: pending);

    await submitHistoricalQuery(tester, api);

    api.authenticatedUserId = _HistoricalQueryApi.ownerB;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: MemoryQueryPage(api: api)),
      ),
    );
    await tester.pump();

    pending.complete(footprintResult(placeName: 'A 私密地点'));
    await tester.pumpAndSettle();

    expect(find.textContaining('A 私密地点'), findsNothing);
    expect(find.text('按日期看足迹'), findsNothing);
  });
}
