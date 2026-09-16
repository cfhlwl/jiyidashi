import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

void main() {
  sqfliteFfiInit();

  late Directory tempDirectory;
  late String databasePath;

  // [人工注释][S1-015] 每个测试使用独立真实 SQLite 文件，close/reopen 才能验证进程重启后的持久化语义。
  setUp(() async {
    tempDirectory = await Directory.systemTemp.createTemp('jiyidashi-offline-');
    databasePath =
        '${tempDirectory.path}${Platform.pathSeparator}offline-queue.sqlite3';
  });

  tearDown(() async {
    await databaseFactoryFfi.deleteDatabase(databasePath);
    if (await tempDirectory.exists()) {
      await tempDirectory.delete(recursive: true);
    }
  });

  OfflineQueueStore createStore() {
    return OfflineQueueStore(
      factory: databaseFactoryFfi,
      databasePathProvider: () async => databasePath,
    );
  }

  test('pending task survives close and reopen with the same client UUID', () async {
    // [人工注释][S1-015] 未发送记录必须真正落盘；重新创建 Store 后仍能读到相同本地任务。
    final firstStore = createStore();
    final created = await firstStore.enqueueTextMemory(
      clientUuid: '11111111-1111-4111-8111-111111111111',
      title: '明天提醒',
      content: '下午三点拿合同',
    );
    expect(created.status, OfflineQueueStatus.pending);
    expect(await firstStore.countAwaitingDelivery(), 1);
    await firstStore.close();

    final reopenedStore = createStore();
    final recovered = await reopenedStore.findByClientUuid(created.clientUuid);
    expect(recovered, isNotNull);
    expect(recovered!.id, created.id);
    expect(recovered.clientUuid, created.clientUuid);
    expect(recovered.payload['content'], '下午三点拿合同');
    expect(recovered.status, OfflineQueueStatus.pending);
    expect(await reopenedStore.countAwaitingDelivery(), 1);
    await reopenedStore.close();
  });

  test('interrupted sending is recovered as failed, never completed', () async {
    // [人工注释][S1-016] sending 时关闭模拟 App 被杀；下次打开必须进入 failed，可重试但绝不能假成功。
    final firstStore = createStore();
    final created = await firstStore.enqueueTextMemory(
      clientUuid: '22222222-2222-4222-8222-222222222222',
      content: '需要可靠恢复的记录',
    );
    final sending = await firstStore.markSending(created.clientUuid);
    expect(sending.status, OfflineQueueStatus.sending);
    expect(sending.attemptCount, 1);
    await firstStore.close();

    final reopenedStore = createStore();
    final recovered = await reopenedStore.findByClientUuid(created.clientUuid);
    expect(recovered, isNotNull);
    expect(recovered!.status, OfflineQueueStatus.failed);
    expect(recovered.attemptCount, 1);
    expect(recovered.completedAt, isNull);
    expect(recovered.lastError, contains('完成确认前中断'));
    await reopenedStore.close();
  });

  test('failed retry reuses one row and one client UUID', () async {
    // [人工注释][S1-016] retryFailed 只改变原任务状态；第二次发送增加 attempt_count，但绝不 insert 新任务。
    final store = createStore();
    final created = await store.enqueueTextMemory(
      clientUuid: '33333333-3333-4333-8333-333333333333',
      content: '同一任务重复尝试',
    );
    await store.markSending(created.clientUuid);
    final failed = await store.markFailed(created.clientUuid, 'network unavailable');
    expect(failed.status, OfflineQueueStatus.failed);
    expect(failed.attemptCount, 1);

    final pendingAgain = await store.retryFailed(created.clientUuid);
    expect(pendingAgain.id, created.id);
    expect(pendingAgain.clientUuid, created.clientUuid);
    expect(pendingAgain.status, OfflineQueueStatus.pending);
    expect(pendingAgain.lastError, isNull);

    final secondSending = await store.markSending(created.clientUuid);
    expect(secondSending.id, created.id);
    expect(secondSending.attemptCount, 2);
    final completed = await store.markCompleted(created.clientUuid);
    expect(completed.status, OfflineQueueStatus.completed);
    expect(completed.completedAt, isNotNull);
    expect(await store.countAwaitingDelivery(), 0);

    final all = await store.listAll();
    expect(all, hasLength(1));
    expect(all.single.clientUuid, created.clientUuid);
    await store.close();
  });

  test('duplicate enqueue is idempotent only for identical local task', () async {
    // [人工注释][S1-016] 相同 UUID + 相同 payload 返回原任务；UUID 冲突但内容不同必须拒绝，避免静默覆盖用户记录。
    final store = createStore();
    const uuid = '44444444-4444-4444-8444-444444444444';
    final first = await store.enqueueTextMemory(
      clientUuid: uuid,
      title: '购物',
      content: '买牛奶',
    );
    final duplicate = await store.enqueueTextMemory(
      clientUuid: uuid,
      title: '购物',
      content: '买牛奶',
    );
    expect(duplicate.id, first.id);
    expect(await store.listAll(), hasLength(1));

    await expectLater(
      store.enqueueTextMemory(
        clientUuid: uuid,
        title: '购物',
        content: '买咖啡',
      ),
      throwsStateError,
    );
    expect(await store.listAll(), hasLength(1));
    await store.close();
  });

  test('cancel is durable and terminal for a local pending task', () async {
    // [人工注释][S1-016] 取消不物理删行：保留确定的 cancelled 语义，且不能再发送或伪装成 completed。
    final firstStore = createStore();
    final created = await firstStore.enqueueTextMemory(
      clientUuid: '55555555-5555-4555-8555-555555555555',
      content: '稍后决定是否发送',
    );
    final cancelled = await firstStore.cancel(created.clientUuid);
    expect(cancelled.status, OfflineQueueStatus.cancelled);
    expect(cancelled.cancelledAt, isNotNull);
    expect(await firstStore.countAwaitingDelivery(), 0);

    final cancelledAgain = await firstStore.cancel(created.clientUuid);
    expect(cancelledAgain.id, created.id);
    await firstStore.close();

    final reopenedStore = createStore();
    final recovered = await reopenedStore.findByClientUuid(created.clientUuid);
    expect(recovered!.status, OfflineQueueStatus.cancelled);
    await expectLater(
      reopenedStore.markSending(created.clientUuid),
      throwsStateError,
    );
    await reopenedStore.close();
  });

  test('schema version is persisted without destructive downgrade policy', () async {
    // [人工注释][S1-015] 首版数据库也必须写入明确 user_version，为未来增量 migration 提供稳定起点。
    final store = createStore();
    await store.enqueueTextMemory(
      clientUuid: '66666666-6666-4666-8666-666666666666',
      content: '验证数据库版本',
    );
    await store.close();

    final database = await databaseFactoryFfi.openDatabase(databasePath);
    expect(await database.getVersion(), OfflineQueueStore.schemaVersion);
    await database.close();
  });
}
