import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/stage1_app.dart';

const captureUserId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const captureClientUuid = '71717171-7171-4171-8171-717171717171';

class _CaptureApi extends JiYiApiClient {
  _CaptureApi(this.failure) : super(baseUrl: 'https://example.invalid/v1') {
    authenticatedUserId = captureUserId;
    accessToken = 'capture-token';
  }

  final Object? failure;
  int calls = 0;

  @override
  Future<Map<String, dynamic>> createTextMemory({
    String? title,
    required String content,
    DateTime? occurredAt,
    String? clientUuid,
  }) async {
    calls += 1;
    final currentFailure = failure;
    if (currentFailure != null) throw currentFailure;
    return {'id': 'memory-$calls'};
  }
}

class _CaptureQueue extends OfflineQueueStore {
  OfflineQueueItem? item;

  OfflineQueueItem _copy(
    OfflineQueueItem current, {
    OfflineQueueStatus? status,
    int? attemptCount,
    bool? retryable,
    String? lastError,
    bool clearLastError = false,
    String? serverResourceId,
    bool clearServerResourceId = false,
    DateTime? completedAt,
  }) {
    return OfflineQueueItem(
      id: current.id,
      ownerUserId: current.ownerUserId,
      clientUuid: current.clientUuid,
      operationType: current.operationType,
      payload: current.payload,
      status: status ?? current.status,
      attemptCount: attemptCount ?? current.attemptCount,
      retryable: retryable ?? current.retryable,
      createdAt: current.createdAt,
      updatedAt: DateTime.utc(2026, 9, 18, 0, 0),
      lastError: clearLastError ? null : (lastError ?? current.lastError),
      serverResourceId: clearServerResourceId
          ? null
          : (serverResourceId ?? current.serverResourceId),
      completedAt: completedAt ?? current.completedAt,
      cancelledAt: current.cancelledAt,
    );
  }

  @override
  Future<OfflineQueueItem> enqueueTextMemory({
    required String ownerUserId,
    String? title,
    required String content,
    DateTime? occurredAt,
    String? clientUuid,
  }) async {
    final existing = item;
    if (existing != null) return existing;
    final timestamp = (occurredAt ?? DateTime.utc(2026, 9, 18, 0, 0)).toUtc();
    final created = OfflineQueueItem(
      id: 1,
      ownerUserId: ownerUserId,
      clientUuid: clientUuid ?? captureClientUuid,
      operationType: OfflineQueueStore.textMemoryOperation,
      payload: {
        if (title != null && title.trim().isNotEmpty) 'title': title.trim(),
        'content': content.trim(),
        'occurred_at': timestamp.toIso8601String(),
      },
      status: OfflineQueueStatus.pending,
      attemptCount: 0,
      retryable: true,
      createdAt: timestamp,
      updatedAt: timestamp,
    );
    item = created;
    return created;
  }

  @override
  Future<List<OfflineQueueItem>> listDeliverable(String ownerUserId) async {
    final current = item;
    if (current == null || current.ownerUserId != ownerUserId) return const [];
    if (current.status == OfflineQueueStatus.pending ||
        (current.status == OfflineQueueStatus.failed && current.retryable)) {
      return [current];
    }
    return const [];
  }

  @override
  Future<OfflineQueueItem> retryFailed(
    String ownerUserId,
    String clientUuid,
  ) async {
    final current = item!;
    final updated = _copy(
      current,
      status: OfflineQueueStatus.pending,
      retryable: true,
      clearLastError: true,
    );
    item = updated;
    return updated;
  }

  @override
  Future<OfflineQueueItem> markSending(
    String ownerUserId,
    String clientUuid,
  ) async {
    final current = item!;
    final updated = _copy(
      current,
      status: OfflineQueueStatus.sending,
      attemptCount: current.attemptCount + 1,
      retryable: true,
      clearLastError: true,
      clearServerResourceId: true,
    );
    item = updated;
    return updated;
  }

  @override
  Future<OfflineQueueItem> markFailed(
    String ownerUserId,
    String clientUuid,
    String error, {
    required bool retryable,
  }) async {
    final current = item!;
    final updated = _copy(
      current,
      status: OfflineQueueStatus.failed,
      retryable: retryable,
      lastError: error,
      clearServerResourceId: true,
    );
    item = updated;
    return updated;
  }

  @override
  Future<OfflineQueueItem> markCompleted(
    String ownerUserId,
    String clientUuid, {
    required String serverResourceId,
  }) async {
    final current = item!;
    final completedAt = DateTime.utc(2026, 9, 18, 0, 1);
    final updated = _copy(
      current,
      status: OfflineQueueStatus.completed,
      retryable: false,
      clearLastError: true,
      serverResourceId: serverResourceId,
      completedAt: completedAt,
    );
    item = updated;
    return updated;
  }

  @override
  Future<OfflineQueueItem?> findByClientUuid(
    String ownerUserId,
    String clientUuid,
  ) async {
    final current = item;
    if (current == null ||
        current.ownerUserId != ownerUserId ||
        current.clientUuid != clientUuid) {
      return null;
    }
    return current;
  }

  @override
  Future<int> countAwaitingDelivery(String ownerUserId) async {
    final current = item;
    if (current == null || current.ownerUserId != ownerUserId) return 0;
    return current.status == OfflineQueueStatus.pending ||
            current.status == OfflineQueueStatus.sending ||
            current.status == OfflineQueueStatus.failed
        ? 1
        : 0;
  }

  @override
  Future<List<OfflineQueueItem>> listAll(String ownerUserId) async {
    final current = item;
    if (current == null || current.ownerUserId != ownerUserId) return const [];
    return [current];
  }

  @override
  Future<void> close() async {}
}

void main() {
  late _CaptureQueue queue;

  setUp(() {
    queue = _CaptureQueue();
  });

  Future<void> pumpCapture(WidgetTester tester, JiYiApiClient api) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CapturePage(api: api, offlineQueue: queue),
        ),
      ),
    );
    await tester.pump();
  }

  Future<void> submitTextMemory(
    WidgetTester tester, {
    String? title,
    required String content,
  }) async {
    final fields = find.byType(TextField);
    if (title != null) {
      await tester.enterText(fields.at(0), title);
    }
    await tester.enterText(fields.at(1), content);
    final button = find.widgetWithText(FilledButton, '帮我记住');
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pump();
  }

  Future<void> pumpUntilFound(WidgetTester tester, Finder finder) async {
    for (var attempt = 0; attempt < 100; attempt++) {
      await tester.pump(const Duration(milliseconds: 25));
      if (finder.evaluate().isNotEmpty) return;
    }
    throw TestFailure('Timed out waiting for expected capture UI state');
  }

  testWidgets('503 keeps the outbox task locally retryable', (tester) async {
    final api = _CaptureApi(ApiException(503, 'temporary outage'));
    await pumpCapture(tester, api);
    await submitTextMemory(
      tester,
      title: '离线标题',
      content: '服务暂时不可用也不能丢',
    );

    await pumpUntilFound(
      tester,
      find.textContaining('已保存到本机，联网后会自动重试'),
    );

    final rows = await queue.listAll(captureUserId);
    expect(rows, hasLength(1));
    expect(rows.single.status, OfflineQueueStatus.failed);
    expect(rows.single.retryable, isTrue);
    expect(rows.single.payload['occurred_at'], isNotNull);
    expect(api.calls, 1);
  });

  testWidgets('422 remains blocked instead of being reported as local success',
      (tester) async {
    final api = _CaptureApi(ApiException(422, '内容不符合要求'));
    await pumpCapture(tester, api);
    await submitTextMemory(tester, content: '这条记录被服务端明确拒绝');

    await pumpUntilFound(
      tester,
      find.text('操作失败：HTTP 422: 内容不符合要求'),
    );

    final rows = await queue.listAll(captureUserId);
    expect(rows, hasLength(1));
    expect(rows.single.status, OfflineQueueStatus.failed);
    expect(rows.single.retryable, isFalse);
  });

  testWidgets('protocol failure is blocked and never becomes completed',
      (tester) async {
    final api = _CaptureApi(ProtocolException('服务端返回格式不正确'));
    await pumpCapture(tester, api);
    await submitTextMemory(tester, content: '协议异常不能假成功');

    await pumpUntilFound(
      tester,
      find.text('操作失败：服务端返回格式不正确'),
    );

    final rows = await queue.listAll(captureUserId);
    expect(rows, hasLength(1));
    expect(rows.single.status, OfflineQueueStatus.failed);
    expect(rows.single.retryable, isFalse);
    expect(rows.single.serverResourceId, isNull);
  });

  testWidgets('successful first flush completes the same persisted outbox row',
      (tester) async {
    final api = _CaptureApi(null);
    await pumpCapture(tester, api);
    await submitTextMemory(tester, content: '先落盘再完成');

    await pumpUntilFound(tester, find.textContaining('✓ 已记住'));

    final rows = await queue.listAll(captureUserId);
    expect(rows, hasLength(1));
    expect(rows.single.status, OfflineQueueStatus.completed);
    expect(rows.single.serverResourceId, 'memory-1');
    expect(api.calls, 1);
  });
}
