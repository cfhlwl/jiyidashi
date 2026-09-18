import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const userA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const userB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

void main() {
  sqfliteFfiInit();
  final testDatabaseFactory = databaseFactoryFfiNoIsolate;

  late Directory tempDirectory;
  late String databasePath;

  setUp(() async {
    tempDirectory = await Directory.systemTemp.createTemp('jiyidashi-offline-');
    databasePath =
        '${tempDirectory.path}${Platform.pathSeparator}offline-queue.sqlite3';
  });

  tearDown(() async {
    await testDatabaseFactory.deleteDatabase(databasePath);
    if (await tempDirectory.exists()) {
      await tempDirectory.delete(recursive: true);
    }
  });

  OfflineQueueStore createStore() {
    return OfflineQueueStore(
      factory: testDatabaseFactory,
      databasePathProvider: () async => databasePath,
    );
  }

  test('pending task survives close and reopen with the same client UUID', () async {
    final firstStore = createStore();
    final created = await firstStore.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '11111111-1111-4111-8111-111111111111',
      title: '明天提醒',
      content: '下午三点拿合同',
    );
    expect(created.ownerUserId, userA);
    expect(created.status, OfflineQueueStatus.pending);
    expect(created.retryable, isTrue);
    expect(await firstStore.countAwaitingDelivery(userA), 1);
    await firstStore.close();

    final reopenedStore = createStore();
    final recovered = await reopenedStore.findByClientUuid(
      userA,
      created.clientUuid,
    );
    expect(recovered, isNotNull);
    expect(recovered!.id, created.id);
    expect(recovered.ownerUserId, userA);
    expect(recovered.clientUuid, created.clientUuid);
    expect(recovered.payload['content'], '下午三点拿合同');
    expect(recovered.status, OfflineQueueStatus.pending);
    expect(recovered.retryable, isTrue);
    expect(await reopenedStore.countAwaitingDelivery(userA), 1);
    await reopenedStore.close();
  });

  test('enqueue freezes text and object event timestamps in payload', () async {
    final store = createStore();
    final occurredAt = DateTime.utc(2026, 9, 17, 2, 30);
    final recordedAt = DateTime.utc(2026, 9, 17, 3, 45);

    final text = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '12121212-1212-4212-8212-121212121212',
      content: '冻结文字发生时间',
      occurredAt: occurredAt,
    );
    final location = await store.enqueueObjectLocation(
      ownerUserId: userA,
      clientUuid: '13131313-1313-4313-8313-131313131313',
      objectName: '护照',
      locationText: '旧抽屉',
      recordedAt: recordedAt,
    );

    expect(text.payload['occurred_at'], occurredAt.toIso8601String());
    expect(location.payload['recorded_at'], recordedAt.toIso8601String());
    await store.close();
  });

  test('interrupted sending is recovered as retryable failed, never completed', () async {
    final firstStore = createStore();
    final created = await firstStore.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '22222222-2222-4222-8222-222222222222',
      content: '需要可靠恢复的记录',
    );
    final sending = await firstStore.markSending(userA, created.clientUuid);
    expect(sending.status, OfflineQueueStatus.sending);
    expect(sending.attemptCount, 1);
    await firstStore.close();

    final reopenedStore = createStore();
    final recovered = await reopenedStore.findByClientUuid(
      userA,
      created.clientUuid,
    );
    expect(recovered, isNotNull);
    expect(recovered!.status, OfflineQueueStatus.failed);
    expect(recovered.retryable, isTrue);
    expect(recovered.attemptCount, 1);
    expect(recovered.completedAt, isNull);
    expect(recovered.serverResourceId, isNull);
    expect(recovered.lastError, contains('完成确认前中断'));
    await reopenedStore.close();
  });

  test('failed retry reuses one row and completed stores server resource id', () async {
    final store = createStore();
    final created = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '33333333-3333-4333-8333-333333333333',
      content: '同一任务重复尝试',
    );
    await store.markSending(userA, created.clientUuid);
    final failed = await store.markFailed(
      userA,
      created.clientUuid,
      'network unavailable',
      retryable: true,
    );
    expect(failed.status, OfflineQueueStatus.failed);
    expect(failed.retryable, isTrue);
    expect(failed.attemptCount, 1);

    final pendingAgain = await store.retryFailed(userA, created.clientUuid);
    expect(pendingAgain.id, created.id);
    expect(pendingAgain.clientUuid, created.clientUuid);
    expect(pendingAgain.status, OfflineQueueStatus.pending);
    expect(pendingAgain.lastError, isNull);

    final secondSending = await store.markSending(userA, created.clientUuid);
    expect(secondSending.id, created.id);
    expect(secondSending.attemptCount, 2);
    final completed = await store.markCompleted(
      userA,
      created.clientUuid,
      serverResourceId: 'memory-server-id',
    );
    expect(completed.status, OfflineQueueStatus.completed);
    expect(completed.retryable, isFalse);
    expect(completed.serverResourceId, 'memory-server-id');
    expect(completed.completedAt, isNotNull);
    expect(await store.countAwaitingDelivery(userA), 0);

    final all = await store.listAll(userA);
    expect(all, hasLength(1));
    expect(all.single.clientUuid, created.clientUuid);
    await store.close();
  });

  test('blocked failed task is excluded from automatic deliverable list', () async {
    final store = createStore();
    final created = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '88888888-8888-4888-8888-888888888888',
      content: '服务端明确拒绝的记录',
    );
    await store.markSending(userA, created.clientUuid);
    final failed = await store.markFailed(
      userA,
      created.clientUuid,
      'HTTP 422',
      retryable: false,
    );
    expect(failed.retryable, isFalse);
    expect(await store.listDeliverable(userA), isEmpty);

    final pending = await store.retryFailed(userA, created.clientUuid);
    expect(pending.status, OfflineQueueStatus.pending);
    expect(pending.retryable, isTrue);
    expect(await store.listDeliverable(userA), hasLength(1));
    await store.close();
  });

  test('duplicate enqueue is idempotent only for identical local task', () async {
    final store = createStore();
    const uuid = '44444444-4444-4444-8444-444444444444';
    final occurredAt = DateTime.utc(2026, 9, 17, 1);
    final first = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: uuid,
      title: '购物',
      content: '买牛奶',
      occurredAt: occurredAt,
    );
    final duplicate = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: uuid,
      title: '购物',
      content: '买牛奶',
      occurredAt: occurredAt,
    );
    expect(duplicate.id, first.id);
    expect(await store.listAll(userA), hasLength(1));

    await expectLater(
      store.enqueueTextMemory(
        ownerUserId: userA,
        clientUuid: uuid,
        title: '购物',
        content: '买咖啡',
        occurredAt: occurredAt,
      ),
      throwsStateError,
    );
    expect(await store.listAll(userA), hasLength(1));
    await store.close();
  });

  test('cancel is durable and terminal for a local pending task', () async {
    final firstStore = createStore();
    final created = await firstStore.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '55555555-5555-4555-8555-555555555555',
      content: '稍后决定是否发送',
    );
    final cancelled = await firstStore.cancel(userA, created.clientUuid);
    expect(cancelled.status, OfflineQueueStatus.cancelled);
    expect(cancelled.retryable, isFalse);
    expect(cancelled.cancelledAt, isNotNull);
    expect(await firstStore.countAwaitingDelivery(userA), 0);

    final cancelledAgain = await firstStore.cancel(userA, created.clientUuid);
    expect(cancelledAgain.id, created.id);
    await firstStore.close();

    final reopenedStore = createStore();
    final recovered = await reopenedStore.findByClientUuid(
      userA,
      created.clientUuid,
    );
    expect(recovered!.status, OfflineQueueStatus.cancelled);
    expect(await reopenedStore.listDeliverable(userA), isEmpty);
    await expectLater(
      reopenedStore.markSending(userA, created.clientUuid),
      throwsStateError,
    );
    await reopenedStore.close();
  });

  test('queue records are isolated by authenticated user id', () async {
    final store = createStore();
    const sharedUuid = '77777777-7777-4777-8777-777777777777';
    final a = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: sharedUuid,
      content: 'A 用户的私有离线记录',
    );
    final b = await store.enqueueTextMemory(
      ownerUserId: userB,
      clientUuid: sharedUuid,
      content: 'B 用户的私有离线记录',
    );

    expect(a.id, isNot(b.id));
    expect((await store.listAll(userA)).single.payload['content'], 'A 用户的私有离线记录');
    expect((await store.listAll(userB)).single.payload['content'], 'B 用户的私有离线记录');
    expect(await store.countAwaitingDelivery(userA), 1);
    expect(await store.countAwaitingDelivery(userB), 1);
    expect((await store.findByClientUuid(userA, sharedUuid))!.ownerUserId, userA);
    expect((await store.findByClientUuid(userB, sharedUuid))!.ownerUserId, userB);
    await store.close();
  });

  test('schema version 2 is persisted without destructive downgrade policy', () async {
    final store = createStore();
    await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '66666666-6666-4666-8666-666666666666',
      content: '验证数据库版本',
    );
    await store.close();

    final database = await testDatabaseFactory.openDatabase(databasePath);
    expect(await database.getVersion(), OfflineQueueStore.schemaVersion);
    final columns = await database.rawQuery('PRAGMA table_info(offline_queue)');
    final names = columns.map((column) => column['name']).toSet();
    expect(names, containsAll(<String>{'retryable', 'server_resource_id'}));
    await database.close();
  });
}
