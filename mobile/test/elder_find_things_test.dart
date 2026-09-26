import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';

void main() {
  testWidgets('Elder find page is explicit and does not query on entry', (tester) async {
    final api = _FindApi();
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(elderMode: true),
        home: MemoryQueryPage(api: api, elderMode: true),
      ),
    );
    await tester.pump();

    expect(find.text('我想找东西'), findsOneWidget);
    expect(find.text('帮我找'), findsOneWidget);
    expect(api.queryCalls, 0);

    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pump();
    expect(find.text('请告诉我你要找什么'), findsOneWidget);
    expect(api.queryCalls, 0);
  });

  testWidgets('Elder no-answer is a first-class no-guess state', (tester) async {
    final api = _FindApi(
      response: {
        'answer': null,
        'can_answer': false,
        'certainty': 'insufficient',
        'reason': 'NO_EVIDENCE',
        'intent': 'FIND_OBJECT',
        'evidence': <Map<String, dynamic>>[],
        'memory_ids': <String>[],
      },
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(elderMode: true),
        home: MemoryQueryPage(api: api, elderMode: true),
      ),
    );

    await tester.enterText(
      find.byKey(const ValueKey('memory-query-input')),
      '护照',
    );
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pumpAndSettle();

    expect(api.queryCalls, 1);
    expect(api.lastQuestion, '护照');
    expect(find.text('我还不知道它在哪里'), findsOneWidget);
    expect(find.textContaining('没有找到足够可靠的记录'), findsOneWidget);
    expect(find.textContaining('可能在'), findsNothing);
    expect(find.textContaining('应该在'), findsNothing);
    expect(find.textContaining('大概在'), findsNothing);
  });

  testWidgets('Elder found state displays canonical server answer and filters AI inference evidence', (tester) async {
    final api = _FindApi(
      response: {
        'answer': '护照在书房抽屉。',
        'can_answer': true,
        'certainty': 'confirmed',
        'reason': null,
        'intent': 'FIND_OBJECT',
        'evidence': [
          {
            'kind': 'OBJECT_LOCATION',
            'id': 'e1',
            'source_type': 'USER_TEXT',
            'memory_source_id': 'm1',
            'occurred_at': '2026-09-26T00:00:00Z',
            'excerpt': '书房抽屉',
            'confidence': 1.0,
          },
          {
            'kind': 'INFERENCE',
            'id': 'e2',
            'source_type': 'AI_INFERENCE',
            'memory_source_id': 'm2',
            'occurred_at': '2026-09-26T00:00:00Z',
            'excerpt': '模型猜测的厨房',
            'confidence': 0.4,
          },
        ],
        'memory_ids': ['memory-1'],
      },
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(elderMode: true),
        home: MemoryQueryPage(api: api, elderMode: true),
      ),
    );

    await tester.enterText(find.byKey(const ValueKey('memory-query-input')), '我的护照在哪里？');
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pumpAndSettle();

    expect(find.text('护照在书房抽屉。'), findsOneWidget);
    expect(find.text('书房抽屉'), findsOneWidget);
    expect(find.text('模型猜测的厨房'), findsNothing);
  });

  testWidgets('rapid repeated Elder find submit is single-flight', (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    final api = _FindApi(pending: pending);
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(elderMode: true),
        home: MemoryQueryPage(api: api, elderMode: true),
      ),
    );

    await tester.enterText(find.byKey(const ValueKey('memory-query-input')), '钥匙');
    final submit = find.byKey(const ValueKey('memory-query-submit'));
    await tester.tap(submit);
    await tester.tap(submit);
    await tester.pump();
    expect(api.queryCalls, 1);

    pending.complete({
      'answer': null,
      'can_answer': false,
      'certainty': 'insufficient',
      'reason': 'NO_EVIDENCE',
      'intent': 'FIND_OBJECT',
      'evidence': <Map<String, dynamic>>[],
      'memory_ids': <String>[],
    });
    await tester.pumpAndSettle();
    expect(api.queryCalls, 1);
  });
}

class _FindApi extends JiYiApiClient {
  _FindApi({this.response, this.pending})
      : super(baseUrl: 'https://find.invalid/v1') {
    accessToken = 'token';
    authenticatedUserId = 'owner-a';
  }

  final Map<String, dynamic>? response;
  final Completer<Map<String, dynamic>>? pending;
  int queryCalls = 0;
  String? lastQuestion;

  @override
  Future<Map<String, dynamic>> queryMemory(String question) async {
    queryCalls += 1;
    lastQuestion = question;
    if (pending != null) return pending!.future;
    return response ??
        {
          'answer': null,
          'can_answer': false,
          'certainty': 'insufficient',
          'reason': 'NO_EVIDENCE',
          'intent': 'FIND_OBJECT',
          'evidence': <Map<String, dynamic>>[],
          'memory_ids': <String>[],
        };
  }
}
