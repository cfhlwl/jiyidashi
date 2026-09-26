import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';

Widget _host(JiYiApiClient api, {required bool elderMode}) => MaterialApp(
      theme: JiYiTheme.light(elderMode: elderMode),
      home: Scaffold(
        body: MemoryQueryPage(api: api, elderMode: elderMode),
      ),
    );

Map<String, dynamic> _noAnswer() => {
      'answer': null,
      'can_answer': false,
      'certainty': 'insufficient',
      'reason': 'NO_EVIDENCE',
      'intent': 'FIND_OBJECT',
      'evidence': <Map<String, dynamic>>[],
      'memory_ids': <String>[],
    };

Map<String, dynamic> _found(String answer) => {
      'answer': answer,
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
          'excerpt': answer,
          'confidence': 1.0,
        },
      ],
      'memory_ids': ['memory-1'],
    };

void main() {
  testWidgets('normal mode query presentation remains unchanged', (tester) async {
    final api = _FindApi();
    await tester.pumpWidget(_host(api, elderMode: false));
    await tester.pump();

    expect(find.text('问记忆'), findsOneWidget);
    expect(find.text('从我的记忆里查找'), findsOneWidget);
    expect(find.text('我想找东西'), findsNothing);
    expect(find.text('帮我找'), findsNothing);
    expect(api.queryCalls, 0);
  });

  testWidgets('Elder find page is explicit and does not query on entry', (tester) async {
    final api = _FindApi();
    await tester.pumpWidget(_host(api, elderMode: true));
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
    final api = _FindApi(response: _noAnswer());
    await tester.pumpWidget(_host(api, elderMode: true));

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
        ..._found('护照在书房抽屉。'),
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
      },
    );
    await tester.pumpWidget(_host(api, elderMode: true));

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
    await tester.pumpWidget(_host(api, elderMode: true));

    await tester.enterText(find.byKey(const ValueKey('memory-query-input')), '钥匙');
    final submit = find.byKey(const ValueKey('memory-query-submit'));
    await tester.tap(submit);
    await tester.tap(submit);
    await tester.pump();
    expect(api.queryCalls, 1);

    pending.complete(_noAnswer());
    await tester.pumpAndSettle();
    expect(api.queryCalls, 1);
  });

  testWidgets('late query result cannot repopulate UI after page disposal', (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    final api = _FindApi(pending: pending);
    await tester.pumpWidget(_host(api, elderMode: true));
    await tester.enterText(find.byKey(const ValueKey('memory-query-input')), '旧查询');
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pump();

    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: Text('replacement'))));
    pending.complete(_found('旧结果绝不能回来'));
    await tester.pumpAndSettle();

    expect(find.text('replacement'), findsOneWidget);
    expect(find.text('旧结果绝不能回来'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('account switch invalidates pending Elder query UI publication', (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    final api = _FindApi(pending: pending);
    await tester.pumpWidget(_host(api, elderMode: true));
    await tester.enterText(find.byKey(const ValueKey('memory-query-input')), 'A 的护照');
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pump();
    expect(api.queryCalls, 1);

    api.logout();
    api.accessToken = 'token-b';
    api.authenticatedUserId = 'owner-b';
    pending.complete(_found('A 的书房'));
    await tester.pumpAndSettle();

    expect(find.text('A 的书房'), findsNothing);
  });

  testWidgets('Elder find query has no write, media, or location side effects', (tester) async {
    final api = _FindApi(response: _noAnswer());
    await tester.pumpWidget(_host(api, elderMode: true));

    await tester.enterText(find.byKey(const ValueKey('memory-query-input')), '钥匙');
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pumpAndSettle();

    expect(api.queryCalls, 1);
    expect(api.textMemoryWrites, 0);
    expect(api.objectLocationWrites, 0);
    expect(api.objectStaleWrites, 0);
    expect(api.mediaUploadCreates, 0);
    expect(api.locationBatchWrites, 0);
  });

  testWidgets('Elder find submit keeps accessible label and enlarged target', (tester) async {
    final api = _FindApi();
    final semantics = tester.ensureSemantics();
    await tester.pumpWidget(_host(api, elderMode: true));
    await tester.pump();

    final submit = find.byKey(const ValueKey('memory-query-submit'));
    final size = tester.getSize(submit);
    expect(size.height, greaterThanOrEqualTo(56));

    final node = tester.getSemantics(submit);
    expect(node.label, contains('帮我找'));
    expect(node.hasAction(SemanticsAction.tap), isTrue);
    semantics.dispose();
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
  int textMemoryWrites = 0;
  int objectLocationWrites = 0;
  int objectStaleWrites = 0;
  int mediaUploadCreates = 0;
  int locationBatchWrites = 0;
  String? lastQuestion;

  @override
  Future<Map<String, dynamic>> queryMemory(String question) async {
    queryCalls += 1;
    lastQuestion = question;
    if (pending != null) return pending!.future;
    return response ?? _noAnswer();
  }

  @override
  Future<Map<String, dynamic>> createTextMemory({
    String? title,
    required String content,
    DateTime? occurredAt,
    String? clientUuid,
  }) async {
    textMemoryWrites += 1;
    throw StateError('find flow must not create Memory');
  }

  @override
  Future<Map<String, dynamic>> rememberObjectLocation({
    required String objectName,
    required String locationText,
    DateTime? recordedAt,
    String? clientUuid,
  }) async {
    objectLocationWrites += 1;
    throw StateError('find flow must not mutate ObjectLocation');
  }

  @override
  Future<Map<String, dynamic>> markObjectLocationStale(String objectName) async {
    objectStaleWrites += 1;
    throw StateError('find flow must not mark ObjectLocation stale');
  }

  @override
  Future<MediaUploadSession> createMediaUpload({
    required String clientUploadId,
    required String kind,
    required String contentType,
    required int sizeBytes,
    String? originalFilename,
  }) async {
    mediaUploadCreates += 1;
    throw StateError('find flow must not create media upload');
  }

  @override
  Future<LocationBatchResult> uploadLocationBatch(
    List<LocationUploadPoint> points,
  ) async {
    locationBatchWrites += 1;
    throw StateError('find flow must not upload location');
  }
}
