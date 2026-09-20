import 'dart:async';
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

  test(
    'account deletion quiesce waits started enqueue and makes purge the last write',
    () async {
      final databasePathRequested = Completer<void>();
      final releaseDatabasePath = Completer<void>();
      final store = OfflineQueueStore(
        factory: testDatabaseFactory,
        databasePathProvider: () async {
          if (!databasePathRequested.isCompleted) {
            databasePathRequested.complete();
          }
          await releaseDatabasePath.future;
          return databasePath;
        },
      );

      // [人工注释][S1-022] 模拟 Capture 已经进入 enqueue，但 SQLite 路径/句柄尚未返回；
      // quiesce 必须把这条“旧 Future”计入在飞写入，而不能让 purge 先返回。
      final delayedEnqueue = store.enqueueTextMemory(
        ownerUserId: userA,
        clientUuid: 'abababab-abab-4bab-8bab-abababababab',
        content: '注销开始前已经点击保存',
      );
      await databasePathRequested.future;

      var quiesced = false;
      final waiting = store
          .quiesceForAccountDeletion(userA)
          .then((_) => quiesced = true);
      await Future<void>.delayed(Duration.zero);
      expect(quiesced, isFalse);

      // ObjectLocation 走同一个 enqueueLocalTask seam；gate 后的新 producer 必须同样拒绝。
      await expectLater(
        store.enqueueObjectLocation(
          ownerUserId: userA,
          clientUuid: 'bcbcbcbc-bcbc-4cbc-8cbc-bcbcbcbcbcbc',
          objectName: '护照',
          locationText: '旧抽屉',
        ),
        throwsStateError,
      );

      releaseDatabasePath.complete();
      await delayedEnqueue;
      await waiting;
      expect(quiesced, isTrue);

      expect(await store.purgeOwner(userA), 1);
      expect(await store.listAll(userA), isEmpty);
      await expectLater(
        store.enqueueTextMemory(
          ownerUserId: userA,
          clientUuid: 'cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd',
          content: '注销 gate 后不能重新写回',
        ),
        throwsStateError,
      );
      expect(await store.listAll(userA), isEmpty);
      await store.close();
    },
  );

  test('account deletion purges only the deleted owner local payloads', () async {
    final store = createStore();
    await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '99999999-9999-4999-8999-999999999999',
      content: 'A must be purged',
    );
    await store.enqueueTextMemory(
      ownerUserId: userB,
      clientUuid: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
      content: 'B must survive',
    );

    expect(await store.purgeOwner(userA), 1);
    expect(await store.listAll(userA), isEmpty);
    expect((await store.listAll(userB)).single.payload['content'], 'B must survive');
    await store.close();
  });

  test('location samples survive reopen and identical UUID enqueue is idempotent', () async {
    const uuid = '10101010-1010-4010-8010-101010101010';
    final recordedAt = DateTime.utc(2026, 9, 20, 0, 15);
    final firstStore = createStore();
    final first = await firstStore.enqueueLocationSample(
      ownerUserId: userA,
      clientUuid: uuid,
      latitude: 3.139,
      longitude: 101.6869,
      accuracyMeters: 18,
      speedMetersPerSecond: 1.4,
      recordedAt: recordedAt,
    );
    final duplicate = await firstStore.enqueueLocationSample(
      ownerUserId: userA,
      clientUuid: uuid,
      latitude: 3.139,
      longitude: 101.6869,
      accuracyMeters: 18,
      speedMetersPerSecond: 1.4,
      recordedAt: recordedAt,
    );
    expect(duplicate.id, first.id);
    expect(await firstStore.countLocationSamples(userA), 1);
    await firstStore.close();

    final reopened = createStore();
    final recovered = await reopened.listLocationSamples(userA);
    expect(recovered, hasLength(1));
    expect(recovered.single.clientUuid, uuid);
    expect(recovered.single.recordedAt, recordedAt);
    await reopened.close();
  });

  test('location UUID conflict and owner isolation fail closed', () async {
    const uuid = '11101010-1010-4010-8010-101010101010';
    final store = createStore();
    final recordedAt = DateTime.utc(2026, 9, 20, 0, 20);
    await store.enqueueLocationSample(
      ownerUserId: userA,
      clientUuid: uuid,
      latitude: 3.1,
      longitude: 101.6,
      recordedAt: recordedAt,
    );
    await expectLater(
      store.enqueueLocationSample(
        ownerUserId: userA,
        clientUuid: uuid,
        latitude: 3.2,
        longitude: 101.6,
        recordedAt: recordedAt,
      ),
      throwsStateError,
    );
    await store.enqueueLocationSample(
      ownerUserId: userB,
      clientUuid: uuid,
      latitude: 3.2,
      longitude: 101.7,
      recordedAt: recordedAt,
    );

    expect((await store.listLocationSamples(userA)).single.latitude, 3.1);
    expect((await store.listLocationSamples(userB)).single.latitude, 3.2);
    await store.close();
  });

  test('location rows delete only by owner and exact stable UUIDs', () async {
    final store = createStore();
    final at = DateTime.utc(2026, 9, 20, 0, 30);
    const first = '12101010-1010-4010-8010-101010101010';
    const second = '13101010-1010-4010-8010-101010101010';
    await store.enqueueLocationSample(
      ownerUserId: userA,
      clientUuid: first,
      latitude: 3.1,
      longitude: 101.6,
      recordedAt: at,
    );
    await store.enqueueLocationSample(
      ownerUserId: userA,
      clientUuid: second,
      latitude: 3.2,
      longitude: 101.7,
      recordedAt: at.add(const Duration(minutes: 1)),
    );
    await store.enqueueLocationSample(
      ownerUserId: userB,
      clientUuid: first,
      latitude: 4.1,
      longitude: 102.6,
      recordedAt: at,
    );

    expect(await store.deleteLocationSamples(userA, <String>[first]), 1);
    expect(
      (await store.listLocationSamples(userA)).map((item) => item.clientUuid),
      <String>[second],
    );
    expect(await store.countLocationSamples(userB), 1);
    await store.close();
  });

  test('account deletion purge also removes raw location outbox for only that owner', () async {
    final store = createStore();
    final at = DateTime.utc(2026, 9, 20, 0, 40);
    await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '14101010-1010-4010-8010-101010101010',
      content: 'delete me',
    );
    await store.enqueueLocationSample(
      ownerUserId: userA,
      clientUuid: '15101010-1010-4010-8010-101010101010',
      latitude: 3.1,
      longitude: 101.6,
      recordedAt: at,
    );
    await store.enqueueLocationSample(
      ownerUserId: userB,
      clientUuid: '16101010-1010-4010-8010-101010101010',
      latitude: 4.1,
      longitude: 102.6,
      recordedAt: at,
    );

    expect(await store.purgeOwner(userA), 2);
    expect(await store.listAll(userA), isEmpty);
    expect(await store.countLocationSamples(userA), 0);
    expect(await store.countLocationSamples(userB), 1);
    await store.close();
  });

  test('schema version 3 is persisted without destructive downgrade policy', () async {
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
    final locationColumns =
        await database.rawQuery('PRAGMA table_info(location_sample_queue)');
    final locationNames =
        locationColumns.map((column) => column['name']).toSet();
    expect(
      locationNames,
      containsAll(<String>{
        'owner_user_id',
        'client_uuid',
        'latitude',
        'longitude',
        'recorded_at',
        'blocked_error',
      }),
    );
    await database.close();
  });
}
