import 'dart:convert';
import 'dart:math';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class PersistedAuthSession {
  const PersistedAuthSession({
    required this.refreshToken,
    required this.sessionId,
  });

  final String refreshToken;
  final String sessionId;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'refresh_token': refreshToken,
        'session_id': sessionId,
      };

  factory PersistedAuthSession.fromJson(Map<String, dynamic> data) {
    final refresh = data['refresh_token'];
    final session = data['session_id'];
    if (refresh is! String ||
        refresh.trim().isEmpty ||
        session is! String ||
        session.trim().isEmpty) {
      throw const FormatException('invalid persisted auth session');
    }
    return PersistedAuthSession(
      refreshToken: refresh,
      sessionId: session,
    );
  }
}

abstract interface class AuthSessionStore {
  Future<PersistedAuthSession?> readSession();
  Future<void> writeSession(PersistedAuthSession session);
  Future<void> clearSession();
  Future<String> readOrCreateInstallationId();
}

class SecureAuthSessionStore implements AuthSessionStore {
  SecureAuthSessionStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  static const _sessionKey = 'jiyi.auth.v1.session';
  static const _installationKey = 'jiyi.auth.v1.installation';

  final FlutterSecureStorage _storage;

  @override
  Future<PersistedAuthSession?> readSession() async {
    final raw = await _storage.read(key: _sessionKey);
    if (raw == null || raw.trim().isEmpty) return null;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) throw const FormatException();
      return PersistedAuthSession.fromJson(decoded);
    } on FormatException {
      // Fail closed on malformed secure state. Keep installation identity but remove
      // unusable credentials so cold start can never infer an owner from corrupted data.
      await clearSession();
      return null;
    }
  }

  @override
  Future<void> writeSession(PersistedAuthSession session) {
    return _storage.write(
      key: _sessionKey,
      value: jsonEncode(session.toJson()),
    );
  }

  @override
  Future<void> clearSession() => _storage.delete(key: _sessionKey);

  @override
  Future<String> readOrCreateInstallationId() async {
    final existing = await _storage.read(key: _installationKey);
    if (existing != null && existing.trim().isNotEmpty) return existing;

    final random = Random.secure();
    final bytes = List<int>.generate(24, (_) => random.nextInt(256));
    final generated = base64UrlEncode(bytes).replaceAll('=', '');
    await _storage.write(key: _installationKey, value: generated);
    return generated;
  }
}

class MemoryAuthSessionStore implements AuthSessionStore {
  PersistedAuthSession? session;
  String? installationId;

  @override
  Future<PersistedAuthSession?> readSession() async => session;

  @override
  Future<void> writeSession(PersistedAuthSession value) async {
    session = value;
  }

  @override
  Future<void> clearSession() async {
    session = null;
  }

  @override
  Future<String> readOrCreateInstallationId() async {
    return installationId ??= 'memory-installation';
  }
}
