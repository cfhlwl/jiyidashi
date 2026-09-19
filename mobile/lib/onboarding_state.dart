import 'dart:io';

import 'package:sqflite/sqflite.dart';

// [人工注释][S1-026] 首次使用引导状态只保存在本机，并严格按服务端 user_id 隔离；不把 UX 状态写进用户 Memory。

enum OnboardingStep {
  intro,
  capture,
  retrieve,
  trust,
}

enum OnboardingStatus {
  inProgress,
  skipped,
  completed,
}

extension OnboardingStatusStorage on OnboardingStatus {
  String get storageValue => switch (this) {
        OnboardingStatus.inProgress => 'in_progress',
        OnboardingStatus.skipped => 'skipped',
        OnboardingStatus.completed => 'completed',
      };

  static OnboardingStatus parse(String value) {
    return switch (value) {
      'in_progress' => OnboardingStatus.inProgress,
      'skipped' => OnboardingStatus.skipped,
      'completed' => OnboardingStatus.completed,
      _ => throw StateError('Unknown onboarding status: $value'),
    };
  }
}

abstract interface class OnboardingStateStore {
  Future<OnboardingStatus?> read(String ownerUserId);
  Future<void> markInProgress(String ownerUserId);
  Future<void> markSkipped(String ownerUserId);
  Future<void> markCompleted(String ownerUserId);
  Future<void> close();
}

// Onboarding completion is device-local but account-scoped. A shared device may host
// several authenticated accounts, so the server user_id is the primary key and no state
// may be inferred from another account's row.
class OnboardingStore implements OnboardingStateStore {
  OnboardingStore({
    DatabaseFactory? factory,
    Future<String> Function()? databasePathProvider,
    DateTime Function()? now,
  })  : _factory = factory,
        _databasePathProvider = databasePathProvider ?? _defaultDatabasePath,
        _now = now ?? DateTime.now;

  static const int schemaVersion = 1;
  static const String databaseFileName = 'jiyidashi_onboarding.sqlite3';

  final DatabaseFactory? _factory;
  final Future<String> Function() _databasePathProvider;
  final DateTime Function() _now;
  Future<Database>? _databaseFuture;

  static Future<String> _defaultDatabasePath() async {
    final base = await getDatabasesPath();
    return '$base${Platform.pathSeparator}$databaseFileName';
  }

  String _normalizeOwner(String ownerUserId) {
    final owner = ownerUserId.trim();
    if (owner.isEmpty) {
      throw ArgumentError.value(
        ownerUserId,
        'ownerUserId',
        'authenticated user ID is required',
      );
    }
    return owner;
  }

  Future<Database> _database() {
    return _databaseFuture ??= () async {
      final factory = _factory ?? databaseFactory;
      return factory.openDatabase(
        await _databasePathProvider(),
        options: OpenDatabaseOptions(
          version: schemaVersion,
          onCreate: (db, version) async {
            await db.execute('''
              CREATE TABLE onboarding_state (
                owner_user_id TEXT PRIMARY KEY NOT NULL,
                status TEXT NOT NULL CHECK (
                  status IN ('in_progress', 'skipped', 'completed')
                ),
                updated_at TEXT NOT NULL
              )
            ''');
          },
        ),
      );
    }();
  }

  @override
  Future<OnboardingStatus?> read(String ownerUserId) async {
    final owner = _normalizeOwner(ownerUserId);
    final db = await _database();
    final rows = await db.query(
      'onboarding_state',
      columns: const ['status'],
      where: 'owner_user_id = ?',
      whereArgs: [owner],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    final value = rows.single['status'];
    if (value is! String) {
      throw StateError('Invalid onboarding status row');
    }
    return OnboardingStatusStorage.parse(value);
  }

  @override
  Future<void> markInProgress(String ownerUserId) =>
      _write(ownerUserId, OnboardingStatus.inProgress);

  @override
  Future<void> markSkipped(String ownerUserId) =>
      _write(ownerUserId, OnboardingStatus.skipped);

  @override
  Future<void> markCompleted(String ownerUserId) =>
      _write(ownerUserId, OnboardingStatus.completed);

  Future<void> _write(
    String ownerUserId,
    OnboardingStatus status,
  ) async {
    final owner = _normalizeOwner(ownerUserId);
    final db = await _database();
    await db.insert(
      'onboarding_state',
      {
        'owner_user_id': owner,
        'status': status.storageValue,
        'updated_at': _now().toUtc().toIso8601String(),
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  @override
  Future<void> close() async {
    final pending = _databaseFuture;
    _databaseFuture = null;
    if (pending != null) {
      final db = await pending;
      await db.close();
    }
  }
}
