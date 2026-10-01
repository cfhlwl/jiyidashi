import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const uuid = '11111111-1111-4111-8111-111111111111';

void main() {
  sqfliteFfiInit();
  final factory = databaseFactoryFfiNoIsolate;
  late Directory tempDirectory;
  late String databasePath;

  setUp(() async {
    tempDirectory = await Directory.systemTemp.createTemp('jiyidashi-core001-store-');
    databasePath =
        '${tempDirectory.path}${Platform.pathSeparator}core001.sqlite3';
  });

  tearDown(() async {
    await factory.deleteDatabase(databasePath);
    if (await tempDirectory.exists()) {
      await tempDirectory.delete(recursive: true);
    }
  });

  test('v3 location queue upgrades to v4 without changing UUID or sequence', () async {
    final legacy = await factory.openDatabase(
      databasePath,
      options: OpenDatabaseOptions(
        version: 3,
        onCreate: (db, version) async {
          await db.execute('''
            CREATE TABLE offline_queue (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              owner_user_id TEXT NOT NULL,
              client_uuid TEXT NOT NULL,
              operation_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              status TEXT NOT NULL,
              attempt_count INTEGER NOT NULL DEFAULT 0,
              last_error TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              completed_at TEXT,
              cancelled_at TEXT,
              retryable INTEGER NOT NULL DEFAULT 1,
              server_resource_id TEXT,
              UNIQUE(owner_user_id, client_uuid)
            )
          ''');
          await db.execute('''
            CREATE TABLE location_sample_queue (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              owner_user_id TEXT NOT NULL,
              client_uuid TEXT NOT NULL,
              latitude REAL NOT NULL,
              longitude REAL NOT NULL,
              accuracy REAL,
              speed REAL,
              recorded_at TEXT NOT NULL,
              blocked_error TEXT,
              created_at TEXT NOT NULL,
              UNIQUE(owner_user_id, client_uuid)
            )
          ''');
          await db.execute('''
            CREATE INDEX idx_location_sample_owner_created
            ON location_sample_queue(owner_user_id, created_at, id)
          ''');
        },
      ),
    );
    const sequence = 41;
    final captured = DateTime.utc(2026, 9, 30, 12);
    await legacy.insert('location_sample_queue', {
      'id': sequence,
      'owner_user_id': owner,
      'client_uuid': uuid,
      'latitude': 3.139,
      'longitude': 101.6869,
      'accuracy': 18.0,
      'speed': 1.5,
      'recorded_at': captured.toIso8601String(),
      'blocked_error': null,
      'created_at': captured.toIso8601String(),
    });
    await legacy.close();

    final store = OfflineQueueStore(
      factory: factory,
      databasePathProvider: () async => databasePath,
    );
    final recovered = await store.listLocationSamples(owner);

    expect(recovered, hasLength(1));
    expect(recovered.single.id, sequence);
    expect(recovered.single.clientUuid, uuid);
    expect(recovered.single.recordedAt, captured);
    expect(recovered.single.attemptCount, 0);
    expect(recovered.single.lastAttemptAt, isNull);
    expect(recovered.single.lastError, isNull);

    final token = await store.tryAcquireLocationDeliveryLease(owner);
    expect(token, isNotNull);
    await store.recordLocationDeliveryAttempt(owner, const [uuid]);
    final attempted = (await store.listLocationSamples(owner)).single;
    expect(attempted.id, sequence);
    expect(attempted.clientUuid, uuid);
    expect(attempted.attemptCount, 1);
    expect(attempted.lastAttemptAt, isNotNull);
    expect(await store.releaseLocationDeliveryLease(owner, token!), isTrue);
    await store.close();

    final raw = await factory.openDatabase(databasePath);
    expect(await raw.getVersion(), OfflineQueueStore.schemaVersion);
    final columns = await raw.rawQuery('PRAGMA table_info(location_sample_queue)');
    final names = columns.map((column) => column['name']).toSet();
    expect(
      names,
      containsAll(<String>{
        'attempt_count',
        'last_attempt_at',
        'last_error',
        'updated_at',
      }),
    );
    await raw.close();
  });

  test('delivery lease is owner-scoped across coordinator instances', () async {
    final first = OfflineQueueStore(
      factory: factory,
      databasePathProvider: () async => databasePath,
    );
    final second = OfflineQueueStore(
      factory: factory,
      databasePathProvider: () async => databasePath,
    );

    final firstToken = await first.tryAcquireLocationDeliveryLease(owner);
    expect(firstToken, isNotNull);
    expect(await second.tryAcquireLocationDeliveryLease(owner), isNull);

    expect(
      await second.releaseLocationDeliveryLease(owner, 'wrong-token'),
      isFalse,
    );
    expect(
      await first.releaseLocationDeliveryLease(owner, firstToken!),
      isTrue,
    );
    expect(await second.tryAcquireLocationDeliveryLease(owner), isNotNull);

    await first.close();
    await second.close();
  });

  test('queue diagnostics persist attempts, failures and authoritative delivery', () async {
    var clock = DateTime.utc(2026, 10, 1, 1);
    final store = OfflineQueueStore(
      factory: factory,
      databasePathProvider: () async => databasePath,
      now: () => clock,
    );
    await store.enqueueLocationSample(
      ownerUserId: owner,
      clientUuid: uuid,
      latitude: 3.139,
      longitude: 101.6869,
      accuracyMeters: 18,
      speedMetersPerSecond: 1.5,
      recordedAt: clock.subtract(const Duration(minutes: 5)),
    );

    await store.recordLocationDeliveryAttempt(owner, const [uuid]);
    clock = clock.add(const Duration(minutes: 1));
    await store.recordLocationDeliveryFailure(
      owner,
      const [uuid],
      'network_unavailable',
    );

    var diagnostics = await store.locationQueueDiagnostics(owner);
    expect(diagnostics.queueDepth, 1);
    expect(diagnostics.blockedCount, 0);
    expect(diagnostics.deliveryFailureCount, 1);
    expect(diagnostics.lastFailureReason, 'network_unavailable');
    expect(diagnostics.oldestPendingAt, isNotNull);
    expect(diagnostics.lastDeliveryAt, isNull);

    clock = clock.add(const Duration(minutes: 1));
    expect(await store.deleteLocationSamples(owner, const [uuid]), 1);
    diagnostics = await store.locationQueueDiagnostics(owner);
    expect(diagnostics.queueDepth, 0);
    expect(diagnostics.lastDeliveryAt, clock);

    await store.close();
  });
}
