import 'dart:io';

import 'package:flutter/material.dart';
import 'package:sqflite/sqflite.dart';

abstract interface class AmapPrivacyConsentAuthority {
  Future<bool> readAccepted();
  Future<void> accept();
  Future<void> revoke();
}

const amapPrivacyDisclosure =
    '地图由高德地图 SDK 提供。启用地图前，我们会向高德提供展示地图所需的设备/网络环境信息，以及迹忆服务端已经形成的地点坐标，用于地图展示、标记和缩放。迹忆不会用设备当前位置替代或猜测你的到访记录。你可以随时在“我的”中撤销地图授权；撤销后将停止创建高德地图视图。';

Future<bool> requestAmapPrivacyConsent(
  BuildContext context,
  AmapPrivacyConsentAuthority authority,
) async {
  final confirmed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('启用高德地图服务'),
          content: const SingleChildScrollView(
            child: Text(amapPrivacyDisclosure),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: const Text('暂不启用'),
            ),
            FilledButton(
              key: const ValueKey('amap-privacy-confirm'),
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: const Text('同意并启用'),
            ),
          ],
        ),
      ) ??
      false;
  if (!confirmed) return false;
  await authority.accept();
  return true;
}

class AmapPrivacyConsentController extends ChangeNotifier
    implements AmapPrivacyConsentAuthority {
  AmapPrivacyConsentController({AmapPrivacyConsentAuthority? delegate})
      : _delegate = delegate ?? AmapPrivacyConsentStore();

  final AmapPrivacyConsentAuthority _delegate;
  bool _accepted = false;
  bool _loaded = false;

  bool get accepted => _loaded && _accepted;

  @override
  Future<bool> readAccepted() async {
    final next = await _delegate.readAccepted();
    final changed = !_loaded || next != _accepted;
    _loaded = true;
    _accepted = next;
    if (changed) notifyListeners();
    return next;
  }

  @override
  Future<void> accept() async {
    await _delegate.accept();
    if (!_loaded || !_accepted) {
      _loaded = true;
      _accepted = true;
      notifyListeners();
    }
  }

  @override
  Future<void> revoke() async {
    await _delegate.revoke();
    if (!_loaded || _accepted) {
      _loaded = true;
      _accepted = false;
      notifyListeners();
    }
  }

  Future<void> close() async {
    final delegate = _delegate;
    if (delegate is AmapPrivacyConsentStore) {
      await delegate.close();
    }
  }
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
