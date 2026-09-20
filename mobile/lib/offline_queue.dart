import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:sqflite/sqflite.dart';

// 队列状态描述本机任务生命周期；可靠同步能力在不破坏这些状态的前提下扩展。
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

// 本地记录继续绑定真实服务端 user_id 与稳定 clientUuid；
// serverResourceId 只有收到服务端权威成功响应后才允许写入 completed。
class OfflineQueueItem {
  const OfflineQueueItem({
    required this.id,
    required this.ownerUserId,
    required this.clientUuid,
    required this.operationType,
    required this.payload,
    required this.status,
    required this.attemptCount,
    required this.retryable,
    required this.createdAt,
    required this.updatedAt,
    this.lastError,
    this.serverResourceId,
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
  final bool retryable;
  final String? lastError;
  final String? serverResourceId;
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
      retryable: ((row['retryable'] as int?) ?? 1) == 1,
      lastError: row['last_error'] as String?,
      serverResourceId: row['server_resource_id'] as String?,
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

class LocationSampleQueueItem {
  const LocationSampleQueueItem({
    required this.id,
    required this.ownerUserId,
    required this.clientUuid,
    required this.latitude,
    required this.longitude,
    required this.recordedAt,
    required this.createdAt,
    this.accuracyMeters,
    this.speedMetersPerSecond,
    this.blockedError,
  });

  final int id;
  final String ownerUserId;
  final String clientUuid;
  final double latitude;
  final double longitude;
  final double? accuracyMeters;
  final double? speedMetersPerSecond;
  final DateTime recordedAt;
  final DateTime createdAt;
  final String? blockedError;

  factory LocationSampleQueueItem.fromRow(Map<String, Object?> row) {
    double? nullableDouble(Object? value) =>
        value == null ? null : (value as num).toDouble();
    return LocationSampleQueueItem(
      id: row['id']! as int,
      ownerUserId: row['owner_user_id']! as String,
      clientUuid: row['client_uuid']! as String,
      latitude: (row['latitude']! as num).toDouble(),
      longitude: (row['longitude']! as num).toDouble(),
      accuracyMeters: nullableDouble(row['accuracy']),
      speedMetersPerSecond: nullableDouble(row['speed']),
      recordedAt: DateTime.parse(row['recorded_at']! as String).toUtc(),
      createdAt: DateTime.parse(row['created_at']! as String).toUtc(),
      blockedError: row['blocked_error'] as String?,
    );
  }
}

// SQLite 继续只允许增量 migration；v3 新增独立 location outbox，
// 不改变 Stage 1 Memory/Object outbox 的资源 ID 完成语义。
class OfflineQueueStore {
  OfflineQueueStore({
    DatabaseFactory? factory,
    Future<String> Function()? databasePathProvider,
    String Function()? clientUuidFactory,
    DateTime Function()? now,
  })  : _factory = factory,
        _databasePathProvider = databasePathProvider ?? _defaultDatabasePath,
        _clientUuidFactory = clientUuidFactory ?? _newClientUuid,
        _now = now ?? DateTime.now;

  static const int schemaVersion = 3;
  static const String databaseFileName = 'jiyidashi_stage1.sqlite3';
  static const String textMemoryOperation = 'text_memory';
  static const String objectLocationOperation = 'object_location';

  final DatabaseFactory? _factory;
  final Future<String> Function() _databasePathProvider;
  final String Function() _clientUuidFactory;
  final DateTime Function() _now;
  Future<Database>? _databaseFuture;
  final Set<String> _accountDeletionQuiescedOwners = <String>{};
  final Map<String, int> _activeEnqueueCounts = <String, int>{};
  final Map<String, Completer<void>> _enqueueIdleWaiters =
      <String, Completer<void>>{};

  static Future<String> _defaultDatabasePath() async {
    final base = await getDatabasesPath();
    return '$base${Platform.pathSeparator}$databaseFileName';
  }

  // UUID v4 在任务首次落盘时生成并永久复用；response-loss 重试不得生成第二个业务键。
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

  Future<void> quiesceForAccountDeletion(String ownerUserId) {
    final owner = _normalizeOwnerUserId(ownerUserId);
    // [人工注释][S1-022] 注销 PREPARE 后必须先封住 owner 的 outbox producer。
    // 已经进入 enqueueLocalTask 的 Future 可以完成，但新的 enqueue 从这里开始全部 fail closed；
    // 调用方等待此 Future 后再 purge，才能保证 purge 是该 owner 最后一次本机 payload 写入。
    _accountDeletionQuiescedOwners.add(owner);
    if ((_activeEnqueueCounts[owner] ?? 0) == 0) {
      return Future<void>.value();
    }
    return (_enqueueIdleWaiters[owner] ??= Completer<void>()).future;
  }

  void _beginEnqueue(String owner) {
    if (_accountDeletionQuiescedOwners.contains(owner)) {
      throw StateError('Offline queue owner is quiesced for account deletion');
    }
    _activeEnqueueCounts[owner] = (_activeEnqueueCounts[owner] ?? 0) + 1;
  }

  void _finishEnqueue(String owner) {
    final remaining = (_activeEnqueueCounts[owner] ?? 0) - 1;
    if (remaining > 0) {
      _activeEnqueueCounts[owner] = remaining;
      return;
    }
    _activeEnqueueCounts.remove(owner);
    final waiter = _enqueueIdleWaiters.remove(owner);
    if (waiter != null && !waiter.isCompleted) {
      waiter.complete();
    }
  }

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
        case 2:
          // retryable 持久化“是否允许后台自动再试”；server_resource_id
          // 只保存服务端权威回执，不能由本地凭空生成。
          await db.execute('''
            ALTER TABLE offline_queue
            ADD COLUMN retryable INTEGER NOT NULL DEFAULT 1
            CHECK (retryable IN (0, 1))
          ''');
          await db.execute('''
            ALTER TABLE offline_queue
            ADD COLUMN server_resource_id TEXT
          ''');
        case 3:
          // Location batch 的服务端协议只返回 aggregate receipt，不返回逐点资源 ID。
          // 因此使用独立 durable outbox：成功前不删行，response-loss 后原 UUID 可安全重放。
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
      }
    }
  }

  Future<void> _recoverInterruptedSending(Database db) async {
    final now = _utcNow().toIso8601String();
    await db.update(
      'offline_queue',
      {
        'status': OfflineQueueStatus.failed.storageValue,
        'retryable': 1,
        'server_resource_id': null,
        'last_error': '上次发送在完成确认前中断，可重试',
        'updated_at': now,
      },
      where: 'status = ?',
      whereArgs: [OfflineQueueStatus.sending.storageValue],
    );
  }

  Future<OfflineQueueItem> enqueueTextMemory({
    required String ownerUserId,
    String? title,
    required String content,
    DateTime? occurredAt,
    String? clientUuid,
  }) {
    final normalizedContent = content.trim();
    if (normalizedContent.isEmpty) {
      throw ArgumentError.value(content, 'content', 'content must not be empty');
    }
    final normalizedTitle = title?.trim();
    final stableOccurredAt = (occurredAt ?? _utcNow()).toUtc();
    return enqueueLocalTask(
      ownerUserId: ownerUserId,
      operationType: textMemoryOperation,
      payload: {
        if (normalizedTitle != null && normalizedTitle.isNotEmpty)
          'title': normalizedTitle,
        'content': normalizedContent,
        'occurred_at': stableOccurredAt.toIso8601String(),
      },
      clientUuid: clientUuid,
    );
  }

  Future<OfflineQueueItem> enqueueObjectLocation({
    required String ownerUserId,
    required String objectName,
    required String locationText,
    DateTime? recordedAt,
    String? clientUuid,
  }) {
    final normalizedObjectName = objectName.trim();
    final normalizedLocationText = locationText.trim();
    if (normalizedObjectName.isEmpty) {
      throw ArgumentError.value(
        objectName,
        'objectName',
        'object name must not be empty',
      );
    }
    if (normalizedLocationText.isEmpty) {
      throw ArgumentError.value(
        locationText,
        'locationText',
        'location text must not be empty',
      );
    }
    final stableRecordedAt = (recordedAt ?? _utcNow()).toUtc();
    return enqueueLocalTask(
      ownerUserId: ownerUserId,
      operationType: objectLocationOperation,
      payload: {
        'object_name': normalizedObjectName,
        'location_text': normalizedLocationText,
        'recorded_at': stableRecordedAt.toIso8601String(),
      },
      clientUuid: clientUuid,
    );
  }

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
      throw ArgumentError.value(
        clientUuid,
        'clientUuid',
        'client UUID must not be empty',
      );
    }
    final payloadJson = jsonEncode(payload);

    // 计数必须在第一次 await 之前登记。这样“已经点击保存、但 SQLite 尚未真正落盘”的
    // Capture Future 会被账号注销 quiesce 等到结束，而 quiesce 之后的新 producer 直接拒绝。
    _beginEnqueue(owner);
    try {
      final db = await _database();
      return await db.transaction((txn) async {
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
          'retryable': 1,
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
    } finally {
      _finishEnqueue(owner);
    }
  }

  Future<LocationSampleQueueItem> enqueueLocationSample({
    required String ownerUserId,
    required String clientUuid,
    required double latitude,
    required double longitude,
    double? accuracyMeters,
    double? speedMetersPerSecond,
    required DateTime recordedAt,
  }) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    final stableUuid = clientUuid.trim();
    if (stableUuid.isEmpty) {
      throw ArgumentError.value(clientUuid, 'clientUuid', 'client UUID must not be empty');
    }
    if (!latitude.isFinite || latitude < -90 || latitude > 90) {
      throw ArgumentError.value(latitude, 'latitude', 'invalid latitude');
    }
    if (!longitude.isFinite || longitude < -180 || longitude > 180) {
      throw ArgumentError.value(longitude, 'longitude', 'invalid longitude');
    }
    if (accuracyMeters != null &&
        (!accuracyMeters.isFinite || accuracyMeters < 0)) {
      throw ArgumentError.value(accuracyMeters, 'accuracyMeters', 'invalid accuracy');
    }
    if (speedMetersPerSecond != null &&
        (!speedMetersPerSecond.isFinite || speedMetersPerSecond < 0)) {
      throw ArgumentError.value(speedMetersPerSecond, 'speedMetersPerSecond', 'invalid speed');
    }

    final stableRecordedAt = recordedAt.toUtc();
    _beginEnqueue(owner);
    try {
      final db = await _database();
      return await db.transaction((txn) async {
        final existingRows = await txn.query(
          'location_sample_queue',
          where: 'owner_user_id = ? AND client_uuid = ?',
          whereArgs: [owner, stableUuid],
          limit: 1,
        );
        if (existingRows.isNotEmpty) {
          final existing = LocationSampleQueueItem.fromRow(existingRows.single);
          final samePayload =
              existing.latitude == latitude &&
              existing.longitude == longitude &&
              existing.accuracyMeters == accuracyMeters &&
              existing.speedMetersPerSecond == speedMetersPerSecond &&
              existing.recordedAt == stableRecordedAt;
          if (!samePayload) {
            throw StateError('location client_uuid already belongs to another sample');
          }
          return existing;
        }

        final createdAt = _utcNow().toIso8601String();
        final id = await txn.insert('location_sample_queue', {
          'owner_user_id': owner,
          'client_uuid': stableUuid,
          'latitude': latitude,
          'longitude': longitude,
          'accuracy': accuracyMeters,
          'speed': speedMetersPerSecond,
          'recorded_at': stableRecordedAt.toIso8601String(),
          'blocked_error': null,
          'created_at': createdAt,
        });
        final rows = await txn.query(
          'location_sample_queue',
          where: 'id = ?',
          whereArgs: [id],
          limit: 1,
        );
        return LocationSampleQueueItem.fromRow(rows.single);
      });
    } finally {
      _finishEnqueue(owner);
    }
  }

  Future<List<LocationSampleQueueItem>> listLocationSamples(
    String ownerUserId, {
    int limit = 100,
  }) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    final db = await _database();
    final rows = await db.query(
      'location_sample_queue',
      where: 'owner_user_id = ? AND blocked_error IS NULL',
      whereArgs: [owner],
      orderBy: 'recorded_at ASC, id ASC',
      limit: limit.clamp(1, 500),
    );
    return rows.map(LocationSampleQueueItem.fromRow).toList(growable: false);
  }

  Future<int> countLocationSamples(String ownerUserId) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    final db = await _database();
    final rows = await db.rawQuery(
      '''
        SELECT COUNT(*) AS total
        FROM location_sample_queue
        WHERE owner_user_id = ? AND blocked_error IS NULL
      ''',
      [owner],
    );
    return (rows.single['total'] as int?) ?? 0;
  }

  Future<int> deleteLocationSamples(
    String ownerUserId,
    List<String> clientUuids,
  ) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    if (clientUuids.isEmpty) return 0;
    final normalized = clientUuids.map((value) => value.trim()).toSet().toList();
    final placeholders = List.filled(normalized.length, '?').join(',');
    final db = await _database();
    return db.delete(
      'location_sample_queue',
      where: 'owner_user_id = ? AND client_uuid IN ($placeholders)',
      whereArgs: [owner, ...normalized],
    );
  }

  Future<int> blockLocationSamples(
    String ownerUserId,
    List<String> clientUuids,
    String error,
  ) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    if (clientUuids.isEmpty) return 0;
    final normalized = clientUuids.map((value) => value.trim()).toSet().toList();
    final placeholders = List.filled(normalized.length, '?').join(',');
    final db = await _database();
    return db.update(
      'location_sample_queue',
      {'blocked_error': error.trim().isEmpty ? 'location upload blocked' : error.trim()},
      where: 'owner_user_id = ? AND client_uuid IN ($placeholders)',
      whereArgs: [owner, ...normalized],
    );
  }

  Future<int> purgeLocationSamples(String ownerUserId) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    final db = await _database();
    return db.delete(
      'location_sample_queue',
      where: 'owner_user_id = ?',
      whereArgs: [owner],
    );
  }

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

  // 自动 flush 只读取 pending 与“明确可重试”的 failed；确定性 4xx/协议错误
  // 会保留在 failed 供用户处理，不会进入后台无限重试。
  Future<List<OfflineQueueItem>> listDeliverable(String ownerUserId) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    final db = await _database();
    final rows = await db.query(
      'offline_queue',
      where: '''
        owner_user_id = ? AND (
          status = ? OR (status = ? AND retryable = 1)
        )
      ''',
      whereArgs: [
        owner,
        OfflineQueueStatus.pending.storageValue,
        OfflineQueueStatus.failed.storageValue,
      ],
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

  Future<int> purgeOwner(String ownerUserId) async {
    final owner = _normalizeOwnerUserId(ownerUserId);
    final db = await _database();
    // 账号注销必须同时删除 Stage 1 outbox 与 Stage 2 raw location outbox。
    // 两张表放在同一事务里，避免崩溃后留下半清理的敏感位置 payload。
    return db.transaction((txn) async {
      final offline = await txn.delete(
        'offline_queue',
        where: 'owner_user_id = ?',
        whereArgs: [owner],
      );
      final location = await txn.delete(
        'location_sample_queue',
        where: 'owner_user_id = ?',
        whereArgs: [owner],
      );
      return offline + location;
    });
  }

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
        'retryable': 1,
        'last_error': null,
        'server_resource_id': null,
        'updated_at': now,
      },
    );
  }

  Future<OfflineQueueItem> markFailed(
    String ownerUserId,
    String clientUuid,
    String error, {
    required bool retryable,
  }) {
    final normalizedError = error.trim();
    return _transition(
      ownerUserId,
      clientUuid,
      allowed: const {OfflineQueueStatus.sending},
      next: OfflineQueueStatus.failed,
      mutate: (_, now) => {
        'retryable': retryable ? 1 : 0,
        'last_error': normalizedError.isEmpty ? '发送失败' : normalizedError,
        'server_resource_id': null,
        'updated_at': now,
        'completed_at': null,
      },
    );
  }

  Future<OfflineQueueItem> markCompleted(
    String ownerUserId,
    String clientUuid, {
    required String serverResourceId,
  }) {
    final resourceId = serverResourceId.trim();
    if (resourceId.isEmpty) {
      throw ArgumentError.value(
        serverResourceId,
        'serverResourceId',
        'completed requires an authoritative server resource ID',
      );
    }
    return _transition(
      ownerUserId,
      clientUuid,
      allowed: const {OfflineQueueStatus.sending},
      next: OfflineQueueStatus.completed,
      mutate: (_, now) => {
        'retryable': 0,
        'last_error': null,
        'server_resource_id': resourceId,
        'updated_at': now,
        'completed_at': now,
      },
    );
  }

  // 手动重试可以显式把 non-retryable failed 恢复 pending；后台自动重试则
  // 只从 listDeliverable 读取 retryable=true 的失败任务。
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
        'retryable': 1,
        'last_error': null,
        'updated_at': now,
      },
    );
  }

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
        'retryable': 0,
        'last_error': null,
        'server_resource_id': null,
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

  Future<void> close() async {
    final pending = _databaseFuture;
    _databaseFuture = null;
    if (pending != null) {
      final db = await pending;
      await db.close();
    }
  }
}
