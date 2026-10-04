import 'dart:io';

import 'package:sqflite/sqflite.dart';

abstract interface class AmapPrivacyConsentAuthority {
  Future<bool> readAccepted();
  Future<void> accept();
  Future<void> revoke();
}

class AmapPrivacyConsentStore implements AmapPrivacyConsentAuthority {
  AmapPrivacyConsentStore({
    DatabaseFactory? factory,
    Future<String> Function()? databasePathProvider,
  })  : _factory = factory,
        _databasePathProvider =
            databasePathProvider ?? _defaultDatabasePath;

  static const databaseFileName = 'jiyidashi_amap_privacy.sqlite3';

  final DatabaseFactory? _factory;
  final Future<String> Function() _databasePathProvider;
  Future<Database>? _databaseFuture;

  static Future<String> _defaultDatabasePath() async {
    final base = await getDatabasesPath();
    return base + Platform.pathSeparator + databaseFileName;
  }

  Future<Database> _database() {
    return _databaseFuture ??= () async {
      final factory = _factory ?? databaseFactory;
      return factory.openDatabase(
        await _databasePathProvider(),
        options: OpenDatabaseOptions(
          version: 1,
          onCreate: (db, version) async {
            await db.execute('''
              CREATE TABLE amap_privacy_consent (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                accepted_at TEXT NOT NULL
              )
            ''');
          },
        ),
      );
    }();
  }

  @override
  Future<bool> readAccepted() async {
    final db = await _database();
    final rows = await db.query(
      'amap_privacy_consent',
      columns: const ['singleton_id'],
      where: 'singleton_id = 1',
      limit: 1,
    );
    return rows.isNotEmpty;
  }

  @override
  Future<void> accept() async {
    final db = await _database();
    await db.insert(
      'amap_privacy_consent',
      <String, Object?>{
        'singleton_id': 1,
        'accepted_at': DateTime.now().toUtc().toIso8601String(),
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  @override
  Future<void> revoke() async {
    final db = await _database();
    await db.delete(
      'amap_privacy_consent',
      where: 'singleton_id = 1',
    );
  }

  Future<void> close() async {
    final pending = _databaseFuture;
    _databaseFuture = null;
    if (pending != null) {
      await (await pending).close();
    }
  }
}
