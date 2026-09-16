import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/stage1_app.dart';

const captureUserId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const captureClientUuid = '77777777-7777-4777-8777-777777777777';

// [人工注释][S1-016] UI 回归用可控 API 故障区分“连接层离线”与“服务端明确拒绝”，防止把真实 4xx/5xx 伪装成本地成功。
class _CaptureApi extends JiYiApiClient {
  _CaptureApi(this.failure) : super(baseUrl: 'https://example.invalid/v1') {
    // [人工注释][S1-015] 测试直接注入认证后的真实 user_id 语义，证明本地记录会绑定当前账号而不是匿名公共队列。
    authenticatedUserId = captureUserId;
  }

  final Object failure;

  @override
  Future<Map<String, dynamic>> createTextMemory({
    String? title,
    required String content,
  }) async {
    throw failure;
  }
}

// [人工注释][S1-015][S1-016] 真实 SQLite 落盘/重启由 offline_queue_test 独立覆盖；这里用可控 Queue seam 只验证 UI 必须等待持久化 Future 完成后才能显示成功。
class _CaptureQueue extends OfflineQueueStore {
  _CaptureQueue({this.deferPersistence = false});

  final bool deferPersistence;
  final Completer<OfflineQueueItem> _writeCompleter =
      Completer<OfflineQueueItem>();
  OfflineQueueItem? storedItem;
  int enqueueCalls = 0;

  OfflineQueueItem _item({
    required String ownerUserId,
    String? title,
    required String content,
  }) {
    final now = DateTime.utc(2026, 9, 16, 0, 0);
    return OfflineQueueItem(
      id: 1,
      ownerUserId: ownerUserId,
      clientUuid: captureClientUuid,
      operationType: OfflineQueueStore.textMemoryOperation,
      payload: {
        if (title != null && title.trim().isNotEmpty) 'title': title.trim(),
        'content': content.trim(),
      },
      status: OfflineQueueStatus.pending,
      attemptCount: 0,
      createdAt: now,
      updatedAt: now,
    );
  }

  @override
  Future<OfflineQueueItem> enqueueTextMemory({
    required String ownerUserId,
    String? title,
    required String content,
    String? clientUuid,
  }) async {
    enqueueCalls += 1;
    final item = _item(
      ownerUserId: ownerUserId,
      title: title,
      content: content,
    );
    if (deferPersistence) {
      final persisted = await _writeCompleter.future;
      storedItem = persisted;
      return persisted;
    }
    storedItem = item;
    return item;
  }

  void completePersistence({
    required String ownerUserId,
    String? title,
    required String content,
  }) {
    _writeCompleter.complete(
      _item(
        ownerUserId: ownerUserId,
        title: title,
        content: content,
      ),
    );
  }

  @override
  Future<int> countAwaitingDelivery(String ownerUserId) async {
    return storedItem?.ownerUserId == ownerUserId ? 1 : 0;
  }

  @override
  Future<List<OfflineQueueItem>> listAll(String ownerUserId) async {
    final item = storedItem;
    if (item == null || item.ownerUserId != ownerUserId) return const [];
    return [item];
  }

  @override
  Future<void> close() async {}
}

void main() {
  late _CaptureQueue queue;

  Future<void> pumpCapture(
    WidgetTester tester,
    JiYiApiClient api,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CapturePage(api: api, offlineQueue: queue),
        ),
      ),
    );
    await tester.pump();
  }

  // [人工注释][S1-016] 输入框获得焦点后光标会持续调度 frame，不能用 pumpAndSettle 等“永远静止”；改为有限等待目标 UI 状态，超时即失败。
  Future<void> pumpUntilFound(
    WidgetTester tester,
    Finder finder,
  ) async {
    for (var attempt = 0; attempt < 100; attempt++) {
      await tester.pump(const Duration(milliseconds: 25));
      if (finder.evaluate().isNotEmpty) return;
    }
    throw TestFailure('Timed out waiting for expected capture UI state');
  }

  testWidgets('connection failure waits for local persistence before success UI',
      (tester) async {
    // [人工注释][S1-015] 网络异常时，持久化 Future 未完成之前禁止显示“已保存到本机”；完成后才清输入并展示待发送状态。
    queue = _CaptureQueue(deferPersistence: true);
    // [人工注释][S1-016] 只有显式 TransportException 才代表可离线降级的连接层失败。
    await pumpCapture(tester, _CaptureApi(TransportException('network down')));
    final fields = find.byType(TextField);
    await tester.enterText(fields.at(0), '离线标题');
    await tester.enterText(fields.at(1), '离线时也不能丢的内容');
    await tester.tap(find.widgetWithText(FilledButton, '帮我记住'));
    await tester.pump();

    expect(queue.enqueueCalls, 1);
    expect(find.textContaining('已保存到本机'), findsNothing);

    queue.completePersistence(
      ownerUserId: captureUserId,
      title: '离线标题',
      content: '离线时也不能丢的内容',
    );
    final savedLocally = find.textContaining('✓ 已保存到本机，待联网后发送');
    await pumpUntilFound(tester, savedLocally);

    expect(savedLocally, findsOneWidget);
    expect(find.text('本机待发送'), findsOneWidget);
    expect(find.textContaining('有 1 条记录已安全保存在本机'), findsOneWidget);
    expect(queue.storedItem?.ownerUserId, captureUserId);
    expect(queue.storedItem?.payload['title'], '离线标题');
    expect(queue.storedItem?.payload['content'], '离线时也不能丢的内容');
  });

  testWidgets('protocol and unexpected client failures are not queued',
      (tester) async {
    // [人工注释][S1-016] 协议异常和未分类运行时异常都必须 fail closed，不能写 SQLite。
    for (final failure in <Object>[
      ProtocolException('服务端返回格式不正确'),
      StateError('unexpected client bug'),
    ]) {
      queue = _CaptureQueue();
      await pumpCapture(tester, _CaptureApi(failure));
      final fields = find.byType(TextField);
      await tester.enterText(fields.at(1), '非 transport 不能排队');
      await tester.tap(find.widgetWithText(FilledButton, '帮我记住'));
      final expected = failure is ProtocolException
          ? '操作失败：服务端返回格式不正确'
          : '操作失败：客户端处理异常';
      await pumpUntilFound(tester, find.text(expected));
      expect(queue.enqueueCalls, 0);
      expect(queue.storedItem, isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets('server ApiException remains a failure and is not queued',
      (tester) async {
    // [人工注释][S1-016] 服务端 422 等明确响应说明请求已到服务端；本地队列不得吞掉错误或显示离线保存成功。
    queue = _CaptureQueue();
    await pumpCapture(tester, _CaptureApi(ApiException(422, '内容不符合要求')));
    final fields = find.byType(TextField);
    await tester.enterText(fields.at(1), '这条记录被服务端拒绝');
    await tester.tap(find.widgetWithText(FilledButton, '帮我记住'));

    final serverFailure = find.text('操作失败：内容不符合要求');
    await pumpUntilFound(tester, serverFailure);

    expect(serverFailure, findsOneWidget);
    expect(find.textContaining('已保存到本机'), findsNothing);
    expect(queue.enqueueCalls, 0);
    expect(queue.storedItem, isNull);
  });
}
