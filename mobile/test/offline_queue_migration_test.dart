import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const clientUuid = '11111111-1111-4111-8111-111111111111';

void main() {
  sqfliteFfiInit();
  final factory = databaseFactoryFfiNoIsolate;
  late Directory tempDirectory;
  late String databasePath;

  setUp(() async {
    tempDirectory = await Directory.systemTemp.createTemp('jiyidashi-v1-upgrade-');
    databasePath =
        '${tempDirectory.path}${Platform.pathSeparator}offline-queue.sqlite3';
  });

  tearDown(() async {
    await factory.deleteDatabase(databasePath);
    if (await tempDirectory.exists()) {
      await tempDirectory.delete(recursive: true);
    }
  });

  test('schema v1 upgrades in place to v2 without losing pending task', () async {
    // 模拟 PR #6 已经存在于真实设备上的 v1 SQLite；
    // F 线只能增量加同步元数据，禁止通过清库/重建丢掉用户尚未发送的本地记录。
    final legacy = await factory.openDatabase(
      databasePath,
      options: OpenDatabaseOptions(
        version: 1,
        onCreate: (db, version) async {
          await db.execute('''
            CREATE TABLE offline_queue (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              owner_user_id TEXT NOT NULL,
              client_uuid TEXT NOT NULL,
              operation_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              status TEXT NOT NULL CHECK (
                status IN ('pending', 'sending', 'failed', 'completed', 'cancelled')
              ),
              attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
              last_error TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              completed_at TEXT,
              cancelled_at TEXT,
              UNIQUE(owner_user_id, client_uuid)
            )
          ''');
          await db.execute('''
            CREATE INDEX idx_offline_queue_owner_status_created
            ON offline_queue(owner_user_id, status, created_at, id)
          ''');
        },
      ),
    );
    final now = DateTime.utc(2026, 9, 17, 12).toIso8601String();
    await legacy.insert('offline_queue', {
      'owner_user_id': owner,
      'client_uuid': clientUuid,
      'operation_type': OfflineQueueStore.textMemoryOperation,
      'payload_json': jsonEncode({'title': '旧任务', 'content': '升级后不能丢'}),
      'status': OfflineQueueStatus.pending.storageValue,
      'attempt_count': 0,
      'created_at': now,
      'updated_at': now,
    });
    expect(await legacy.getVersion(), 1);
    await legacy.close();

    final upgraded = OfflineQueueStore(
      factory: factory,
      databasePathProvider: () async => databasePath,
    );
    final recovered = await upgraded.findByClientUuid(owner, clientUuid);

    expect(recovered, isNotNull);
    expect(recovered!.ownerUserId, owner);
    expect(recovered.clientUuid, clientUuid);
    expect(recovered.payload['title'], '旧任务');
    expect(recovered.payload['content'], '升级后不能丢');
    expect(recovered.status, OfflineQueueStatus.pending);
    expect(recovered.retryable, isTrue);
    expect(recovered.serverResourceId, isNull);
    expect(await upgraded.listDeliverable(owner), hasLength(1));
    await upgraded.close();

    final raw = await factory.openDatabase(databasePath);
    expect(await raw.getVersion(), OfflineQueueStore.schemaVersion);
    final columns = await raw.rawQuery('PRAGMA table_info(offline_queue)');
    final names = columns.map((column) => column['name']).toSet();
    expect(names, containsAll(<String>{'retryable', 'server_resource_id'}));
    await raw.close();
  });
}
