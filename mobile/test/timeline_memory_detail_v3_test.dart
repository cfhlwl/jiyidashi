import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/memory_detail_page.dart';
import 'package:jiyidashi/stage1_app.dart';

const _batch3Owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const _batch3Memory = '11111111-1111-4111-8111-111111111111';

class _Batch3Api extends JiYiApiClient {
  _Batch3Api({this.timelineItems = const []})
      : super(baseUrl: 'https://batch3.invalid/v1') {
    accessToken = 'token';
    authenticatedUserId = _batch3Owner;
  }

  final List<Map<String, dynamic>> timelineItems;
  final List<String> reminderMemoryIds = <String>[];

  @override
  Future<Map<String, dynamic>> getTimelineEvents({
    int limit = 30,
    String? cursor,
    String? day,
  }) async {
    return <String, dynamic>{
      'timezone': 'Asia/Shanghai',
      'day': null,
      'items': timelineItems,
      'next_cursor': null,
    };
  }

  @override
  Future<Map<String, dynamic>> getMemory(String memoryId) async {
    return <String, dynamic>{
      'id': memoryId,
      'user_id': _batch3Owner,
      'memory_type': 'NOTE',
      'title': '真实记忆标题',
      'content': '真实记忆正文，不由页面猜测。',
      'occurred_at': '2026-10-08T08:20:00+08:00',
      'place_id': null,
      'metadata_json': const <String, dynamic>{},
      'edit_revision': 4,
    };
  }

  @override
  Future<Map<String, dynamic>> createReminder({
    required String memoryId,
    required String title,
    String? content,
    required DateTime remindAt,
    required String clientUuid,
  }) async {
    reminderMemoryIds.add(memoryId);
    return <String, dynamic>{'id': 'reminder-1'};
  }
}

Map<String, dynamic> _timelineMemory({
  String title = '真实时间线记录',
}) {
  return <String, dynamic>{
    'kind': 'MEMORY',
    'id': _batch3Memory,
    'occurred_at': '2026-10-08T08:20:00+08:00',
    'ended_at': null,
    'place_id': null,
    'place_name': null,
    'memory_type': 'NOTE',
    'title': title,
    'content': '来自 API 的真实正文。',
    'is_confirmed': true,
    'confidence': 1.0,
    'media_id': null,
    'visit_finalized': null,
  };
}

Future<void> _pumpAt(
  WidgetTester tester,
  Widget child, {
  Size size = const Size(390, 844),
  double textScale = 1.0,
}) async {
  await tester.binding.setSurfaceSize(size);
  await tester.pumpWidget(
    MediaQuery(
      data: MediaQueryData(size: size, textScaler: TextScaler.linear(textScale)),
      child: MaterialApp(home: child),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('Timeline renders trusted records and remains navigable on small screens',
      (tester) async {
    final api = _Batch3Api(timelineItems: [_timelineMemory()]);
    await _pumpAt(tester, TimelinePage(api: api), size: const Size(320, 568));

    expect(find.text('时间线'), findsOneWidget);
    expect(find.text('真实时间线记录'), findsOneWidget);
    expect(find.text('来自 API 的真实正文。'), findsOneWidget);
    expect(find.text('MEMORY'), findsNothing);
    expect(find.text(_batch3Memory), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Memory Detail reminder cancel does not create a reminder',
      (tester) async {
    final api = _Batch3Api();
    await _pumpAt(tester, MemoryDetailPage(api: api, memoryId: _batch3Memory));

    final entry = find.byKey(const ValueKey('memory-reminder-entry'));
    expect(entry, findsOneWidget);
    await tester.tap(entry);
    await tester.pumpAndSettle();

    expect(find.text('为这条记忆设置提醒'), findsOneWidget);
    expect(find.textContaining('绑定这条原始记忆'), findsOneWidget);
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(api.reminderMemoryIds, isEmpty);
  });

  testWidgets('Memory Detail reminder save uses canonical memory ID',
      (tester) async {
    final api = _Batch3Api();
    await _pumpAt(tester, MemoryDetailPage(api: api, memoryId: _batch3Memory));

    await tester.tap(find.byKey(const ValueKey('memory-reminder-entry')));
    await tester.pumpAndSettle();
    expect(find.text('为这条记忆设置提醒'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('reminder-save')));
    await tester.pumpAndSettle();

    expect(api.reminderMemoryIds, [_batch3Memory]);
    expect(api.reminderMemoryIds, hasLength(1));
  });

  testWidgets('Memory Detail keeps primary actions reachable with large text',
      (tester) async {
    final api = _Batch3Api();
    await _pumpAt(
      tester,
      MemoryDetailPage(api: api, memoryId: _batch3Memory),
      size: const Size(390, 844),
      textScale: 1.4,
    );

    expect(find.byKey(const ValueKey('memory-reminder-entry')), findsOneWidget);
    expect(find.text('编辑'), findsOneWidget);
    expect(find.text('删除'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
