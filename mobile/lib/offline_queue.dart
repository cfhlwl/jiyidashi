import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:sqflite/sqflite.dart';

// [人工注释][S1-016] 队列状态只描述本机任务生命周期；真正联网同步、服务端幂等与自动重试留给 S1-017。
enum OfflineQueueStatus {
  pending,
  sending,
  failed,
  completed,
  cancelled,
}

extension OfflineQueueStatusStorage on OfflineQueueStatus {
  String get storageValue => name;

  static OfflineQueueStatus parse(String value) {
    return OfflineQueueStatus.values.firstWhere(
      (status) => status.storageValue == value,
      orElse: () => throw StateError('Unknown offline queue status: $value'),
    );
  }
}

// [人工注释][S1-015] 本地记录必须绑定真实服务端 user_id，并保留稳定 clientUuid、原始 payload 与状态；本地状态不冒充服务端 Memory。
class OfflineQueueItem {
  const OfflineQueueItem({
    required this.id,
    required this.ownerUserId,
    required this.clientUuid,
    required this.operationType,
    required this.payload,
    required this.status,
    required this.attemptCount,
    required this.createdAt,
    required this.updatedAt,
    this.lastError,
    this.completedAt,
    this.cancelledAt,
  });

  final int id;
  final String ownerUserId;
  final String clientUuid;
  final String operationType;
  final Map<String, dynamic> payload;
  final OfflineQueueStatus status;
  final int attemptCount;
  final String? lastError;
  final DateTime createdAt;
  final DateTime updatedAt;
  final DateTime? completedAt;
  final DateTime? cancelledAt;

  bool get isTerminal =>
      status == OfflineQueueStatus.completed ||
      status == OfflineQueueStatus.cancelled;

  factory OfflineQueueItem.fromRow(Map<String, Object?> row) {
    final decoded = jsonDecode(row['payload_json']! as String);
    if (decoded is! Map<String, dynamic>) {
      throw StateError('Offline queue payload is not a JSON object');
    }
    return OfflineQueueItem(
      id: row['id']! as int,
      ownerUserId: row['owner_user_id']! as String,
      clientUuid: row['client_uuid']! as String,
      operationType: row['operation_type']! as String,
      payload: decoded,
      status: OfflineQueueStatusStorage.parse(row['status']! as String),
      attemptCount: row['attempt_count']! as int,
      lastError: row['last_error'] as String?,
      createdAt: DateTime.parse(row['created_at']! as String),
      updatedAt: DateTime.parse(row['updated_at']! as String),
      completedAt: _parseNullableDate(row['completed_at']),
      cancelledAt: _parseNullableDate(row['cancelled_at']),
    );
  }

  static DateTime? _parseNullableDate(Object? value) {
    return value == null ? null : DateTime.parse(value as String);
  }
}

// [人工注释][S1-015] SQLite 版本固定从 migration 入口升级；未来 schema 版本只能增量迁移，禁止依赖清库重装。
class OfflineQueueStore {
  OfflineQueueStore({
    DatabaseFactory? factory,
    Future<String> Function()? databasePathProvider,
    String Function()? clientUuidFactory,
    DateTime Function()? now,
  })  : _factory = factory,
        _databasePathProvider =
            databasePathProvider ?? _defaultDatabasePath,
        _clientUuidFactory = clientUuidFactory ?? _newClientUuid,
        _now = now ?? DateTime.now;

  static const int schemaVersion = 1;
  static const String databaseFileName = 'jiyidashi_stage1.sqlite3';
  static const String textMemoryOperation = 'text_memory';

  final DatabaseFactory? _factory;
  final Future<String> Function() _databasePathProvider;
  final String Function() _clientUuidFactory;
  final DateTime Function() _now;
  Future<Database>? _databaseFuture;

  // [人工注释][S1-015] 生产库放在系统数据库目录；测试可注入独立路径与 DatabaseFactory，不共享真实用户数据。
  static Future<String> _defaultDatabasePath() async {
    final base = await getDatabasesPath();
    return '$base${Platform.pathSeparator}$databaseFileName';
  }

  // [人工注释][S1-016] UUID v4 在任务首次落盘时生成并永久复用；失败重试不得生成第二个本地任务 ID。
  static String _newClientUuid() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    final hex = bytes.map((value) => value.toRadixString(16).padLeft(2, '0')).join();
    return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
        '${hex.substring(12, 16)}-${hex.substring(16, 20)}-'
        '${hex.substring(20)}';
  }

  DateTime _utcNow() => _now().toUtc();

  String _normalizeOwnerUserId(String ownerUserId) {
    final normalized = ownerUserId.trim();
    if (normalized.isEmpty) {
      throw ArgumentError.value(
        ownerUserId,
        'ownerUserId',
        'owner user ID must not be empty',
      );
    }
    return normalized;
  }

  // [人工注释][S1-015] 只有真正首次访问 SQLite 时才解析平台 databaseFactory；纯 UI/认证测试不应被未初始化的数据库插件耦合。
  Future<Database> _database() {
    return _databaseFuture ??= () async {
      final factory = _factory ?? databaseFactory;
      final database = await factory.openDatabase(
        await _databasePathProvider(),
        options: OpenDatabaseOptions(
          version: schemaVersion,
          onCreate: (db, version) => _migrate(db, 0, version),
          onUpgrade: _migrate,
        ),
      );
      await _recoverInterruptedSending(database);
      return database;
    }();
  }

  Future<void> _migrate(Database db, int oldVersion, int newVersion) async {
    for (var version = oldVersion + 1; version <= newVersion; version++) {
      switch (version) {
        case 1:
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
      }
    }
  }

  // [人工注释][S1-016] App 在 sending 中崩溃/被杀后，重启必须显式降为 failed；绝不能把未确认发送结果伪装成 completed。
  Future<void> _recoverInterruptedSending(Database db) async {
    final now = _utcNow().toIso8601String();
    await db.update(
      'offline_queue',
      {
        'status': OfflineQueueStatus.failed.storageValue,
        'last_error': '上次发送在完成确认前中断，可重试',
        'updated_at': now,
      },
      where: 'status = ?',
      whereArgs: [OfflineQueueStatus.sending.storageValue],
    );
  }

  // [人工注释][S1-016] 当前只验证稳定的文字记录本地结构；payload 是本地格式，不新增或修改 Backend 媒体/API 字段。
  Future<OfflineQueueItem> enqueueTextMemory({
    required String ownerUserId,
    String? title,
    required String content,
    String? clientUuid,
  }) {
    final normalizedContent = content.trim();
    if (normalizedContent.isEmpty) {
      throw ArgumentError.value(content, 'content', 'content must not be empty');
    }
    final normalizedTitle = title?.trim();
    return enqueueLocalTask(
      ownerUserId: ownerUserId,
      operationType: textMemoryOperation,
      payload: {
        if (normalizedTitle != null && normalizedTitle.isNotEmpty)
          'title': normalizedTitle,
        'content': normalizedContent,
      },
      clientUuid: clientUuid,
    );
  }

  // [人工注释][S1-016] 入队事务同时按真实 user_id 与 client_uuid 隔离/去重；同账号相同 UUID 不允许被不同内容静默覆盖。
  Future<OfflineQueueItem> enqueueLocalTask({
    required String ownerUserId,
    required String operationType,
    required Map<String, dynamic> payload,
    String? clientUuid,
  }) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    final normalizedType = operationType.trim();
    if (normalizedType.isEmpty) {
      throw ArgumentError.value(
        operationType,
        'operationType',
        'operation type must not be empty',
      );
    }
    final stableUuid = (clientUuid ?? _clientUuidFactory()).trim();
    if (stableUuid.isEmpty) {
      throw ArgumentError.value(clientUuid, 'clientUuid', 'client UUID must not be empty');
    }
    final payloadJson = jsonEncode(payload);
    final db = await _database();
    return db.transaction((txn) async {
      final existingRows = await txn.query(
        'offline_queue',
        where: 'owner_user_id = ? AND client_uuid = ?',
        whereArgs: [owner, stableUuid],
        limit: 1,
      );
      if (existingRows.isNotEmpty) {
        final existing = OfflineQueueItem.fromRow(existingRows.single);
        if (existing.operationType != normalizedType ||
            jsonEncode(existing.payload) != payloadJson) {
          throw StateError('client_uuid already belongs to another local task');
        }
        return existing;
      }

      final now = _utcNow().toIso8601String();
      final id = await txn.insert('offline_queue', {
        'owner_user_id': owner,
        'client_uuid': stableUuid,
        'operation_type': normalizedType,
        'payload_json': payloadJson,
        'status': OfflineQueueStatus.pending.storageValue,
        'attempt_count': 0,
        'created_at': now,
        'updated_at': now,
      });
      final rows = await txn.query(
        'offline_queue',
        where: 'id = ?',
        whereArgs: [id],
        limit: 1,
      );
      return OfflineQueueItem.fromRow(rows.single);
    });
  }

  // [人工注释][S1-016] 重启恢复与后续 S1-017 调度均按 user_id 从 SQLite 读取真实队列，不维护易丢失或跨账号的内存镜像。
  Future<List<OfflineQueueItem>> listAll(String ownerUserId) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    final db = await _database();
    final rows = await db.query(
      'offline_queue',
      where: 'owner_user_id = ?',
      whereArgs: [owner],
      orderBy: 'created_at ASC, id ASC',
    );
    return rows.map(OfflineQueueItem.fromRow).toList(growable: false);
  }

  Future<OfflineQueueItem?> findByClientUuid(
    String ownerUserId,
    String clientUuid,
  ) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    final db = await _database();
    final rows = await db.query(
      'offline_queue',
      where: 'owner_user_id = ? AND client_uuid = ?',
      whereArgs: [owner, clientUuid],
      limit: 1,
    );
    return rows.isEmpty ? null : OfflineQueueItem.fromRow(rows.single);
  }

  // [人工注释][S1-016] UI 只统计当前登录用户仍需处理的本机任务；其他账号以及 completed/cancelled 均不可见。
  Future<int> countAwaitingDelivery(String ownerUserId) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    final db = await _database();
    final result = await db.rawQuery(
      '''
        SELECT COUNT(*) AS total
        FROM offline_queue
        WHERE owner_user_id = ? AND status IN (?, ?, ?)
      ''',
      [
        owner,
        OfflineQueueStatus.pending.storageValue,
        OfflineQueueStatus.sending.storageValue,
        OfflineQueueStatus.failed.storageValue,
      ],
    );
    return (result.single['total'] as int?) ?? 0;
  }

  // [人工注释][S1-016] pending -> sending 才增加 attempt_count；重试先把同一条 failed 任务恢复 pending，再由发送动作计数。
  Future<OfflineQueueItem> markSending(
    String ownerUserId,
    String clientUuid,
  ) {
    return _transition(
      ownerUserId,
      clientUuid,
      allowed: const {OfflineQueueStatus.pending},
      next: OfflineQueueStatus.sending,
      mutate: (current, now) => {
        'attempt_count': current.attemptCount + 1,
        'last_error': null,
        'updated_at': now,
      },
    );
  }

  // [人工注释][S1-016] 只有 sending 能进入 failed，错误原因持久化供重启后展示/诊断；失败绝不写 completed_at。
  Future<OfflineQueueItem> markFailed(
    String ownerUserId,
    String clientUuid,
    String error,
  ) {
    final normalizedError = error.trim();
    return _transition(
      ownerUserId,
      clientUuid,
      allowed: const {OfflineQueueStatus.sending},
      next: OfflineQueueStatus.failed,
      mutate: (_, now) => {
        'last_error': normalizedError.isEmpty ? '发送失败' : normalizedError,
        'updated_at': now,
        'completed_at': null,
      },
    );
  }

  // [人工注释][S1-016] completed 只能来自 sending 的明确成功确认；本轮不实现产生该确认的网络同步器。
  Future<OfflineQueueItem> markCompleted(
    String ownerUserId,
    String clientUuid,
  ) {
    return _transition(
      ownerUserId,
      clientUuid,
      allowed: const {OfflineQueueStatus.sending},
      next: OfflineQueueStatus.completed,
      mutate: (_, now) => {
        'last_error': null,
        'updated_at': now,
        'completed_at': now,
      },
    );
  }

  // [人工注释][S1-016] failed -> pending 在同账号原行原 client_uuid 上重试，不 insert 新任务，因此不会制造本地重复记录。
  Future<OfflineQueueItem> retryFailed(
    String ownerUserId,
    String clientUuid,
  ) {
    return _transition(
      ownerUserId,
      clientUuid,
      allowed: const {OfflineQueueStatus.failed},
      next: OfflineQueueStatus.pending,
      mutate: (_, now) => {
        'last_error': null,
        'updated_at': now,
      },
    );
  }

  // [人工注释][S1-016] 取消采用软状态：当前用户的 pending/failed 可取消，sending/completed 不允许假装取消；重复取消保持幂等。
  Future<OfflineQueueItem> cancel(
    String ownerUserId,
    String clientUuid,
  ) async {
    final current = await findByClientUuid(ownerUserId, clientUuid);
    if (current == null) {
      throw StateError('Offline queue item not found: $clientUuid');
    }
    if (current.status == OfflineQueueStatus.cancelled) {
      return current;
    }
    return _transition(
      ownerUserId,
      clientUuid,
      allowed: const {
        OfflineQueueStatus.pending,
        OfflineQueueStatus.failed,
      },
      next: OfflineQueueStatus.cancelled,
      mutate: (_, now) => {
        'last_error': null,
        'updated_at': now,
        'cancelled_at': now,
      },
    );
  }

  Future<OfflineQueueItem> _transition(
    String ownerUserId,
    String clientUuid, {
    required Set<OfflineQueueStatus> allowed,
    required OfflineQueueStatus next,
    required Map<String, Object?> Function(
      OfflineQueueItem current,
      String now,
    ) mutate,
  }) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    final db = await _database();
    return db.transaction((txn) async {
      final rows = await txn.query(
        'offline_queue',
        where: 'owner_user_id = ? AND client_uuid = ?',
        whereArgs: [owner, clientUuid],
        limit: 1,
      );
      if (rows.isEmpty) {
        throw StateError('Offline queue item not found: $clientUuid');
      }
      final current = OfflineQueueItem.fromRow(rows.single);
      if (!allowed.contains(current.status)) {
        throw StateError(
          'Invalid offline queue transition: ${current.status.name} -> ${next.name}',
        );
      }
      final now = _utcNow().toIso8601String();
      await txn.update(
        'offline_queue',
        {
          'status': next.storageValue,
          ...mutate(current, now),
        },
        where: 'id = ? AND owner_user_id = ?',
        whereArgs: [current.id, owner],
      );
      final updated = await txn.query(
        'offline_queue',
        where: 'id = ? AND owner_user_id = ?',
        whereArgs: [current.id, owner],
        limit: 1,
      );
      return OfflineQueueItem.fromRow(updated.single);
    });
  }

  // [人工注释][S1-015] close 只释放句柄，不删库；下次打开必须仍能恢复未完成记录。
  Future<void> close() async {
    final pending = _databaseFuture;
    _databaseFuture = null;
    if (pending != null) {
      final db = await pending;
      await db.close();
    }
  }
}
