import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/stage1_app.dart';

class _MemoryEditApi extends JiYiApiClient {
  _MemoryEditApi({
    this.intent = 'MEMORY_SEARCH',
    this.conflictOnUpdate = false,
  }) : super(baseUrl: 'https://example.test/v1');

  final String intent;
  final bool conflictOnUpdate;
  int queryCalls = 0;
  int getCalls = 0;
  int updateCalls = 0;
  String? updatedTitle;
  String? updatedContent;
  int? updatedExpectedRevision;

  @override
  Future<Map<String, dynamic>> queryMemory(String question) async {
    queryCalls += 1;
    final edited = updateCalls > 0;
    return {
      'answer': edited ? '最相关的一条是：修正后的正文' : '最相关的一条是：原始正文',
      'can_answer': true,
      'certainty': 'evidence',
      'reason': null,
      'intent': intent,
      'evidence': [
        {
          'kind': 'MEMORY',
          'id': '11111111-1111-1111-1111-111111111111',
          'source_type': 'USER_TEXT',
          'memory_source_id': edited
              ? '33333333-3333-3333-3333-333333333333'
              : '22222222-2222-2222-2222-222222222222',
          'provenance': edited ? 'USER_EDIT' : 'ORIGINAL_SOURCE',
          'occurred_at': '2026-09-19T00:00:00Z',
          'excerpt': edited ? '修正后的正文' : '原始正文',
          'confidence': 1.0,
          'media_id': null,
        }
      ],
      'memory_ids': ['11111111-1111-1111-1111-111111111111'],
    };
  }

  @override
  Future<Map<String, dynamic>> getMemory(String memoryId) async {
    getCalls += 1;
    return {
      'id': memoryId,
      'title': '原始标题',
      'content': '原始正文',
      'edit_revision': 4,
    };
  }

  @override
  Future<Map<String, dynamic>> updateMemory(
    String memoryId, {
    required int expectedRevision,
    String? title,
    required String content,
  }) async {
    updateCalls += 1;
    if (conflictOnUpdate) {
      throw ApiException(409, 'MEMORY_EDIT_REVISION_CONFLICT');
    }
    updatedExpectedRevision = expectedRevision;
    updatedTitle = title;
    updatedContent = content;
    return {
      'id': memoryId,
      'title': title,
      'content': content,
      'edit_revision': 1,
    };
  }
}

Future<void> _openEditDialog(
  WidgetTester tester,
  _MemoryEditApi api,
) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(body: MemoryQueryPage(api: api)),
    ),
  );
  await tester.enterText(find.byType(TextField).first, '测试记忆');
  await tester.tap(find.text('从我的记忆里查找'));
  await tester.pumpAndSettle();
  await tester.ensureVisible(find.byKey(const ValueKey('memory-edit-open')));
  // ensureVisible 会驱动滚动位置；等布局稳定后再 hit-test，避免测试点击旧坐标。
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const ValueKey('memory-edit-open')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('editing a queried memory reloads server query and marks edit evidence',
      (tester) async {
    final api = _MemoryEditApi();
    await _openEditDialog(tester, api);

    expect(api.getCalls, 1);
    expect(find.byKey(const ValueKey('memory-edit-title')), findsOneWidget);
    expect(find.byKey(const ValueKey('memory-edit-content')), findsOneWidget);

    await tester.enterText(
      find.byKey(const ValueKey('memory-edit-title')),
      '修正标题',
    );
    await tester.enterText(
      find.byKey(const ValueKey('memory-edit-content')),
      '修正后的正文',
    );
    await tester.tap(find.byKey(const ValueKey('memory-edit-save')));
    await tester.pumpAndSettle();

    expect(api.updateCalls, 1);
    expect(api.updatedExpectedRevision, 4);
    expect(api.updatedTitle, '修正标题');
    expect(api.updatedContent, '修正后的正文');
    expect(api.queryCalls, 2);
    expect(find.textContaining('记忆已更新'), findsOneWidget);
    expect(find.textContaining('修正后的正文'), findsWidgets);
    // provenance 来自服务端；UI 只明确展示“用户编辑”，不自行改变 Evidence 类型。
    expect(find.textContaining('用户编辑'), findsOneWidget);
  });

  testWidgets('structured object result hides unsupported generic edit action',
      (tester) async {
    final api = _MemoryEditApi(intent: 'FIND_OBJECT');
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: MemoryQueryPage(api: api)),
      ),
    );
    await tester.enterText(find.byType(TextField).first, '护照在哪里');
    await tester.tap(find.text('从我的记忆里查找'));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('memory-edit-open')), findsNothing);
    expect(find.text('删除最相关记忆'), findsOneWidget);
  });

  testWidgets('revision conflict asks user to re-query instead of exposing raw code',
      (tester) async {
    final api = _MemoryEditApi(conflictOnUpdate: true);
    await _openEditDialog(tester, api);

    await tester.enterText(
      find.byKey(const ValueKey('memory-edit-content')),
      '我这边的过期修改',
    );
    await tester.tap(find.byKey(const ValueKey('memory-edit-save')));
    await tester.pumpAndSettle();

    expect(api.updateCalls, 1);
    expect(find.text('这条记忆已经在其他地方更新，请重新查询后再编辑'), findsOneWidget);
    expect(find.text('MEMORY_EDIT_REVISION_CONFLICT'), findsNothing);
  });

  testWidgets('memory edit dialog rejects blank content before PATCH', (tester) async {
    final api = _MemoryEditApi();
    await _openEditDialog(tester, api);

    await tester.enterText(
      find.byKey(const ValueKey('memory-edit-content')),
      '   ',
    );
    await tester.tap(find.byKey(const ValueKey('memory-edit-save')));
    await tester.pump();

    expect(find.text('内容不能为空'), findsOneWidget);
    expect(api.updateCalls, 0);
    expect(find.byKey(const ValueKey('memory-edit-save')), findsOneWidget);
  });
}
