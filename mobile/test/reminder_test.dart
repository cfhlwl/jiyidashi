import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/reminder_page.dart';
import 'package:jiyidashi/stage1_app.dart';

class _ReminderApi extends JiYiApiClient {
  _ReminderApi() : super(baseUrl: 'https://example.test/v1');

  String? createdMemoryId;
  String? createdTitle;
  String? createdContent;
  DateTime? createdRemindAt;
  final List<String> createKeys = [];
  final List<String?> listStatuses = [];
  bool failFirstCreateAsResponseLoss = false;
  int completeCalls = 0;
  int cancelCalls = 0;

  List<Map<String, dynamic>> rows = [
    {
      'id': 'r1',
      'memory_id': '11111111-1111-1111-1111-111111111111',
      'title': '待完成提醒',
      'content': '第一条',
      'remind_at': '2026-09-20T01:00:00Z',
      'status': 'PENDING',
    },
    {
      'id': 'r2',
      'memory_id': '11111111-1111-1111-1111-111111111111',
      'title': '历史提醒',
      'content': null,
      'remind_at': '2026-09-18T01:00:00Z',
      'status': 'DONE',
    },
    {
      'id': 'r3',
      'memory_id': '11111111-1111-1111-1111-111111111111',
      'title': '待取消提醒',
      'content': null,
      'remind_at': '2026-09-21T01:00:00Z',
      'status': 'PENDING',
    },
  ];

  @override
  Future<Map<String, dynamic>> queryMemory(String question) async {
    return {
      'answer': '最相关的一条是：周五前提交材料',
      'can_answer': true,
      'certainty': 'evidence',
      'reason': null,
      'intent': 'MEMORY_SEARCH',
      'evidence': [
        {
          'kind': 'MEMORY',
          'id': '11111111-1111-1111-1111-111111111111',
          'source_type': 'USER_TEXT',
          'memory_source_id': '22222222-2222-2222-2222-222222222222',
          'provenance': 'ORIGINAL_SOURCE',
          'occurred_at': '2026-09-19T00:00:00Z',
          'excerpt': '周五前提交材料',
          'confidence': 1.0,
          'media_id': null,
        }
      ],
      'memory_ids': ['11111111-1111-1111-1111-111111111111'],
    };
  }

  @override
  Future<Map<String, dynamic>> getMemory(String memoryId) async {
    return {
      'id': memoryId,
      'title': '交材料',
      'content': '周五前提交材料',
      'edit_revision': 0,
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
    createdMemoryId = memoryId;
    createdTitle = title;
    createdContent = content;
    createdRemindAt = remindAt;
    createKeys.add(clientUuid);
    if (failFirstCreateAsResponseLoss && createKeys.length == 1) {
      throw Exception('synthetic response loss');
    }
    return {
      'id': 'r-new',
      'memory_id': memoryId,
      'title': title,
      'content': content,
      'remind_at': remindAt.toUtc().toIso8601String(),
      'status': 'PENDING',
    };
  }

  @override
  Future<List<Map<String, dynamic>>> listReminders({
    String? status,
    int limit = 100,
  }) async {
    listStatuses.add(status);
    return rows
        .where((row) => status == null || row['status'] == status)
        .take(limit)
        .map((row) => Map<String, dynamic>.from(row))
        .toList();
  }

  @override
  Future<Map<String, dynamic>> completeReminder(String reminderId) async {
    completeCalls += 1;
    rows = rows
        .map(
          (row) => row['id'] == reminderId
              ? {...row, 'status': 'DONE'}
              : row,
        )
        .toList();
    return rows.firstWhere((row) => row['id'] == reminderId);
  }

  @override
  Future<Map<String, dynamic>> cancelReminder(String reminderId) async {
    cancelCalls += 1;
    rows = rows
        .map(
          (row) => row['id'] == reminderId
              ? {...row, 'status': 'CANCELLED'}
              : row,
        )
        .toList();
    return rows.firstWhere((row) => row['id'] == reminderId);
  }
}

Future<void> _pumpReminderDialogFrame(WidgetTester tester) async {
  // [人工注释][S1-025] 创建 Reminder 时父页面保持 loading=true，背景进度环会持续调度 frame。
  // 因此弹窗打开/response-loss 保持打开的阶段不能用 pumpAndSettle；只推进确定的 route 动画帧。
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));
}

void main() {
  testWidgets('query result can create a memory-linked reminder', (tester) async {
    final api = _ReminderApi();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: MemoryQueryPage(api: api)),
      ),
    );

    await tester.enterText(find.byType(TextField).first, '交材料');
    await tester.tap(find.text('从我的记忆里查找'));
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.byKey(const ValueKey('memory-reminder-open')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('memory-reminder-open')));
    await _pumpReminderDialogFrame(tester);

    expect(find.byKey(const ValueKey('reminder-title')), findsOneWidget);
    expect(find.text('交材料'), findsWidgets);

    final before = DateTime.now();
    await tester.tap(find.byKey(const ValueKey('reminder-save')));
    await _pumpReminderDialogFrame(tester);

    expect(find.byKey(const ValueKey('reminder-title')), findsNothing);
    expect(find.textContaining('提醒已设置'), findsOneWidget);
    expect(
      api.createdMemoryId,
      '11111111-1111-1111-1111-111111111111',
    );
    expect(api.createdTitle, '交材料');
    expect(api.createKeys, hasLength(1));
    expect(
      RegExp(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
      ).hasMatch(api.createKeys.single),
      isTrue,
    );
    expect(api.createdRemindAt, isNotNull);
    expect(
      api.createdRemindAt!.isAfter(
        before.add(const Duration(minutes: 59)),
      ),
      isTrue,
    );
  });

  testWidgets('response-loss retry reuses the same create key and frozen time',
      (tester) async {
    final api = _ReminderApi()..failFirstCreateAsResponseLoss = true;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: MemoryQueryPage(api: api)),
      ),
    );

    await tester.enterText(find.byType(TextField).first, '交材料');
    await tester.tap(find.text('从我的记忆里查找'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const ValueKey('memory-reminder-open')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('memory-reminder-open')));
    await _pumpReminderDialogFrame(tester);

    await tester.tap(find.byKey(const ValueKey('reminder-save')));
    await _pumpReminderDialogFrame(tester);
    expect(find.byKey(const ValueKey('reminder-title')), findsOneWidget);
    expect(find.textContaining('安全重试'), findsOneWidget);
    expect(api.createKeys, hasLength(1));
    final firstKey = api.createKeys.single;
    final firstTime = api.createdRemindAt;

    await tester.tap(find.byKey(const ValueKey('reminder-save')));
    await _pumpReminderDialogFrame(tester);

    expect(find.byKey(const ValueKey('reminder-title')), findsNothing);
    expect(find.textContaining('提醒已设置'), findsOneWidget);
    expect(api.createKeys, [firstKey, firstKey]);
    expect(api.createdRemindAt, firstTime);
  });

  testWidgets('reminder management loads pending separately from large history',
      (tester) async {
    final api = _ReminderApi();
    final now = DateTime.parse('2026-09-19T00:00:00Z');
    api.rows = [
      {
        'id': 'old-pending',
        'memory_id': '11111111-1111-1111-1111-111111111111',
        'title': '不能被历史挤掉',
        'content': null,
        'remind_at': '2026-09-25T01:00:00Z',
        'created_at': now.subtract(const Duration(days: 1)).toIso8601String(),
        'status': 'PENDING',
      },
      for (var index = 0; index < 120; index++)
        {
          'id': 'history-$index',
          'memory_id': null,
          'title': '历史-$index',
          'content': null,
          'remind_at': '2026-09-20T01:00:00Z',
          'created_at': now.add(Duration(minutes: index)).toIso8601String(),
          'status': index.isEven ? 'DONE' : 'CANCELLED',
        },
    ];

    await tester.pumpWidget(
      MaterialApp(home: ReminderPage(api: api)),
    );
    await tester.pumpAndSettle();

    expect(api.listStatuses, containsAll(['PENDING', 'DONE', 'CANCELLED']));
    expect(find.text('不能被历史挤掉'), findsOneWidget);
    expect(find.text('当前没有待处理提醒。'), findsNothing);
  });

  testWidgets('reminder management transitions then reloads split lists',
      (tester) async {
    final api = _ReminderApi();
    await tester.pumpWidget(
      MaterialApp(home: ReminderPage(api: api)),
    );
    await tester.pumpAndSettle();

    expect(find.text('待完成提醒'), findsOneWidget);
    expect(find.text('历史提醒'), findsOneWidget);
    expect(find.text('待取消提醒'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('reminder-done-r1')));
    await tester.pumpAndSettle();
    expect(api.completeCalls, 1);

    await tester.ensureVisible(find.byKey(const ValueKey('reminder-cancel-r3')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('reminder-cancel-r3')));
    await tester.pumpAndSettle();
    expect(api.cancelCalls, 1);
  });

}
