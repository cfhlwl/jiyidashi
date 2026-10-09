import 'dart:async';
import 'dart:convert';
import 'dart:developer' as developer;
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'auth_session_store.dart';
import 'auth_v3.dart';
import 'phone_one_tap_bridge.dart';
import 'sms_otp.dart';

const _appEnv = String.fromEnvironment('APP_ENV', defaultValue: 'development');
const _configuredApiBaseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: '');
const _developmentApiBaseUrl = 'http://127.0.0.1:8000/v1';

String _resolveApiBaseUrl(String? override) {
  if (override != null && override.trim().isNotEmpty) {
    return override.replaceFirst(RegExp(r'/$'), '');
  }
  if (_configuredApiBaseUrl.trim().isNotEmpty) {
    return _configuredApiBaseUrl.replaceFirst(RegExp(r'/$'), '');
  }
  // [人工注释][S1-FIX-007] production 构建禁止静默回退 localhost；必须通过 dart-define 明确注入真实 API。
  if (_appEnv == 'production') {
    throw StateError('API_BASE_URL is required for production builds');
  }
  return _developmentApiBaseUrl;
}

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);

  final int statusCode;
  final String message;

  @override
  String toString() => message;
}

// [人工注释][S1-016] 只有 HTTP 客户端明确报告的连接/传输失败或超时才属于可离线降级的 transport；协议/解析错误不得进入该类型。
class TransportException implements Exception {
  TransportException(this.message, [this.cause]);
  final String message;
  final Object? cause;
  @override
  String toString() => message;
}

// [人工注释][S1-016] 2xx 响应已到达但 JSON/结构不符合正式协议时必须 fail closed，禁止误判为离线。
class ProtocolException implements Exception {
  ProtocolException(this.message, [this.cause]);
  final String message;
  final Object? cause;
  @override
  String toString() => message;
}

class _AuthenticatedSessionSnapshot {
  const _AuthenticatedSessionSnapshot({
    required this.accessToken,
    required this.userId,
    required this.sessionId,
    required this.sessionVersion,
  });

  final String accessToken;
  final String userId;
  final String? sessionId;
  final int sessionVersion;
}

class AccountDeleteSessionBinding {
  const AccountDeleteSessionBinding._(this._snapshot);

  final _AuthenticatedSessionSnapshot _snapshot;

  String get ownerUserId => _snapshot.userId;
}

class PushSessionBinding {
  const PushSessionBinding._(this._snapshot);

  final _AuthenticatedSessionSnapshot _snapshot;

  String get ownerUserId => _snapshot.userId;
  int get sessionVersion => _snapshot.sessionVersion;
}

class SignedUploadTarget {
  const SignedUploadTarget({
    required this.method,
    required this.url,
    required this.headers,
  });

  final String method;
  final Uri url;
  final Map<String, String> headers;
}

class SignedDownloadTarget {
  const SignedDownloadTarget({
    required this.method,
    required this.url,
    required this.headers,
    required this.expiresAt,
  });

  final String method;
  final Uri url;
  final Map<String, String> headers;
  final DateTime expiresAt;

  factory SignedDownloadTarget.fromJson(Map<String, dynamic> data) {
    final method = data['method'];
    final rawUrl = data['url'];
    final rawHeaders = data['headers'];
    final rawExpiresAt = data['expires_at'];
    final url = rawUrl is String ? Uri.tryParse(rawUrl) : null;
    final expiresAt =
        rawExpiresAt is String ? DateTime.tryParse(rawExpiresAt)?.toUtc() : null;
    if (method is! String ||
        method.toUpperCase() != 'GET' ||
        url == null ||
        !url.hasScheme ||
        (url.scheme != 'https' && url.scheme != 'http') ||
        rawHeaders is! Map<String, dynamic> ||
        expiresAt == null) {
      throw ProtocolException('服务端返回格式不正确');
    }
    final headers = <String, String>{};
    for (final entry in rawHeaders.entries) {
      if (entry.value is! String) {
        throw ProtocolException('服务端返回格式不正确');
      }
      headers[entry.key] = entry.value as String;
    }
    return SignedDownloadTarget(
      method: method.toUpperCase(),
      url: url,
      headers: Map<String, String>.unmodifiable(headers),
      expiresAt: expiresAt,
    );
  }
}

class MediaDownloadSession {
  const MediaDownloadSession({
    required this.mediaId,
    required this.cacheVersion,
    required this.download,
  });

  final String mediaId;
  final String cacheVersion;
  final SignedDownloadTarget download;
}

class MediaUploadSession {
  const MediaUploadSession({required this.mediaId, required this.upload});

  final String mediaId;
  final SignedUploadTarget? upload;

  factory MediaUploadSession.fromJson(Map<String, dynamic> data) {
    final mediaId = data['id'];
    if (mediaId is! String || mediaId.trim().isEmpty) {
      throw ProtocolException('服务端返回格式不正确');
    }
    final rawUpload = data['upload'];
    if (rawUpload == null) {
      return MediaUploadSession(mediaId: mediaId, upload: null);
    }
    if (rawUpload is! Map<String, dynamic>) {
      throw ProtocolException('服务端返回格式不正确');
    }
    final method = rawUpload['method'];
    final url = rawUpload['url'];
    final rawHeaders = rawUpload['headers'];
    if (method is! String ||
        method.toUpperCase() != 'PUT' ||
        url is! String ||
        url.trim().isEmpty ||
        rawHeaders is! Map<String, dynamic>) {
      throw ProtocolException('服务端返回格式不正确');
    }
    final headers = <String, String>{};
    for (final entry in rawHeaders.entries) {
      if (entry.value is! String) {
        throw ProtocolException('服务端返回格式不正确');
      }
      headers[entry.key] = entry.value as String;
    }
    return MediaUploadSession(
      mediaId: mediaId,
      upload: SignedUploadTarget(
        method: method.toUpperCase(),
        url: Uri.parse(url),
        headers: headers,
      ),
    );
  }
}

class LocationUploadPoint {
  const LocationUploadPoint({
    required this.clientUuid,
    required this.latitude,
    required this.longitude,
    required this.recordedAt,
    this.accuracyMeters,
    this.speedMetersPerSecond,
  });

  final String clientUuid;
  final double latitude;
  final double longitude;
  final double? accuracyMeters;
  final double? speedMetersPerSecond;
  final DateTime recordedAt;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'client_uuid': clientUuid,
        'latitude': latitude,
        'longitude': longitude,
        if (accuracyMeters != null) 'accuracy': accuracyMeters,
        if (speedMetersPerSecond != null) 'speed': speedMetersPerSecond,
        'recorded_at': recordedAt.toUtc().toIso8601String(),
      };
}

class LocationBatchResult {
  const LocationBatchResult({
    required this.accepted,
    required this.duplicates,
    required this.rejectedPrivacy,
    required this.rejectedFinalized,
  });

  final int accepted;
  final int duplicates;
  final int rejectedPrivacy;
  final int rejectedFinalized;

  int get terminalCount =>
      accepted + duplicates + rejectedPrivacy + rejectedFinalized;

  factory LocationBatchResult.fromJson(Map<String, dynamic> data) {
    int requiredInt(String key) {
      final value = data[key];
      if (value is int && value >= 0) return value;
      throw ProtocolException('服务端位置批量响应格式不正确');
    }

    return LocationBatchResult(
      accepted: requiredInt('accepted'),
      duplicates: requiredInt('duplicates'),
      rejectedPrivacy: requiredInt('rejected_privacy'),
      rejectedFinalized: requiredInt('rejected_finalized'),
    );
  }
}

bool _strictDateOnly(String value) {
  final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch(value);
  if (match == null) return false;
  final year = int.parse(match.group(1)!);
  final month = int.parse(match.group(2)!);
  final day = int.parse(match.group(3)!);
  final parsed = DateTime.utc(year, month, day);
  return parsed.year == year && parsed.month == month && parsed.day == day;
}

bool _strictIsoDateTime(String value) {
  final match = RegExp(
    r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$',
  ).firstMatch(value);
  if (match == null || !_strictDateOnly(value.substring(0, 10))) return false;
  final hour = int.parse(match.group(4)!);
  final minute = int.parse(match.group(5)!);
  final second = int.parse(match.group(6)!);
  return hour <= 23 &&
      minute <= 59 &&
      second <= 59 &&
      DateTime.tryParse(value) != null;
}

Map<String, dynamic>? _parseQueryDayFootprint(Object? raw) {
  if (raw == null) return null;
  if (raw is! Map<String, dynamic>) {
    throw ProtocolException('服务端查询响应格式不正确');
  }
  final timezone = raw['timezone'];
  final day = raw['day'];
  final empty = raw['empty'];
  final visits = raw['visits'];
  if (timezone is! String ||
      timezone.trim().isEmpty ||
      day is! String ||
      !_strictDateOnly(day) ||
      empty is! bool ||
      visits is! List<dynamic>) {
    throw ProtocolException('服务端查询响应格式不正确');
  }

  final parsedVisits = <Map<String, dynamic>>[];
  for (final item in visits) {
    if (item is! Map<String, dynamic>) {
      throw ProtocolException('服务端查询响应格式不正确');
    }
    final id = item['id'];
    final placeId = item['place_id'];
    final placeName = item['place_name'];
    final arrivedAt = item['arrived_at'];
    final leftAt = item['left_at'];
    final arrivedAtLocal = item['arrived_at_local'];
    final leftAtLocal = item['left_at_local'];
    final confidence = item['confidence'];
    final visitSource = item['visit_source'];
    final finalized = item['visit_finalized'];
    if (id is! String ||
        id.trim().isEmpty ||
        placeId is! String ||
        placeId.trim().isEmpty ||
        placeName is! String ||
        placeName.trim().isEmpty ||
        arrivedAt is! String ||
        !_strictIsoDateTime(arrivedAt) ||
        (leftAt != null &&
            (leftAt is! String || !_strictIsoDateTime(leftAt))) ||
        arrivedAtLocal is! String ||
        !_strictIsoDateTime(arrivedAtLocal) ||
        (leftAtLocal != null &&
            (leftAtLocal is! String || !_strictIsoDateTime(leftAtLocal))) ||
        confidence is! num ||
        !confidence.isFinite ||
        visitSource is! String ||
        visitSource.trim().isEmpty ||
        finalized is! bool) {
      throw ProtocolException('服务端查询响应格式不正确');
    }
    parsedVisits.add(Map<String, dynamic>.unmodifiable(item));
  }
  if (empty != parsedVisits.isEmpty) {
    throw ProtocolException('服务端查询响应格式不正确');
  }
  return Map<String, dynamic>.unmodifiable({
    'timezone': timezone,
    'day': day,
    'empty': empty,
    'visits': List<Map<String, dynamic>>.unmodifiable(parsedVisits),
  });
}

Map<String, dynamic> _parseMemoryQueryResult(Map<String, dynamic> data) {
  final answer = data['answer'];
  final canAnswer = data['can_answer'];
  final certainty = data['certainty'];
  final reason = data['reason'];
  final intent = data['intent'];
  final evidence = data['evidence'];
  final memoryIds = data['memory_ids'];
  final parsedDayFootprint = _parseQueryDayFootprint(data['day_footprint']);
  if ((answer != null && answer is! String) ||
      canAnswer is! bool ||
      certainty is! String ||
      (reason != null && reason is! String) ||
      intent is! String ||
      evidence is! List<dynamic> ||
      memoryIds is! List<dynamic>) {
    throw ProtocolException('服务端查询响应格式不正确');
  }
  if (canAnswer && (answer is! String || answer.trim().isEmpty)) {
    throw ProtocolException('服务端查询响应格式不正确');
  }

  final parsedEvidence = <Map<String, dynamic>>[];
  for (final item in evidence) {
    if (item is! Map<String, dynamic>) {
      throw ProtocolException('服务端查询响应格式不正确');
    }
    final confidence = item['confidence'];
    if (item['kind'] is! String ||
        item['id'] is! String ||
        item['source_type'] is! String ||
        item['memory_source_id'] is! String ||
        item['occurred_at'] is! String ||
        item['excerpt'] is! String ||
        confidence is! num ||
        !confidence.isFinite) {
      throw ProtocolException('服务端查询响应格式不正确');
    }
    final provenance = item['provenance'];
    if (provenance != null &&
        provenance != 'ORIGINAL_SOURCE' &&
        provenance != 'USER_EDIT') {
      throw ProtocolException('服务端查询响应格式不正确');
    }
    parsedEvidence.add(Map<String, dynamic>.unmodifiable(item));
  }

  final parsedIds = <String>[];
  for (final id in memoryIds) {
    if (id is! String || id.trim().isEmpty) {
      throw ProtocolException('服务端查询响应格式不正确');
    }
    parsedIds.add(id);
  }

  final parsed = Map<String, dynamic>.unmodifiable({
    'answer': answer,
    'can_answer': canAnswer,
    'certainty': certainty,
    if (reason != null) 'reason': reason,
    'intent': intent,
    'evidence': List<Map<String, dynamic>>.unmodifiable(parsedEvidence),
    'memory_ids': List<String>.unmodifiable(parsedIds),
    if (parsedDayFootprint != null) 'day_footprint': parsedDayFootprint,
  });

  final hasStructuredFootprint =
      parsedDayFootprint != null &&
      (parsedDayFootprint['visits'] as List<dynamic>).isNotEmpty;
  final canonicalEvidenceAnswer =
      canAnswer == true &&
      answer is String &&
      answer.trim().isNotEmpty &&
      (certainty == 'confirmed' || certainty == 'evidence') &&
      parsedEvidence.isNotEmpty &&
      parsedIds.isNotEmpty;
  final canonicalStructuredAnswer =
      canAnswer == true &&
      answer is String &&
      answer.trim().isNotEmpty &&
      (certainty == 'confirmed' || certainty == 'evidence') &&
      hasStructuredFootprint;
  final structuredNoEvidenceExplanation =
      parsedDayFootprint != null ||
      reason == 'INVALID_DATE' ||
      reason == 'FUTURE_DATE';
  final canonicalNoEvidence =
      canAnswer == false &&
      (answer == null ||
          (structuredNoEvidenceExplanation &&
              answer is String &&
              answer.trim().isNotEmpty)) &&
      certainty == 'unknown' &&
      parsedEvidence.isEmpty &&
      parsedIds.isEmpty &&
      (parsedDayFootprint == null ||
          (parsedDayFootprint['visits'] as List<dynamic>).isEmpty);
  if (!canonicalEvidenceAnswer &&
      !canonicalStructuredAnswer &&
      !canonicalNoEvidence) {
    throw ProtocolException('服务端查询响应格式不正确');
  }
  return parsed;
}

enum AuthRestoreStatus {
  restored,
  noPersistedSession,
  serverUnavailable,
  invalidSession,
}

const Set<String> _terminalDurableSessionErrorCodes = <String>{
  'INVALID_REFRESH_TOKEN',
  'REFRESH_TOKEN_REUSED',
  'AUTH_SESSION_REVOKED',
  'REFRESH_TOKEN_EXPIRED',
  'AUTH_ACCOUNT_UNAVAILABLE',
  'AUTH_SESSION_INVALID',
};

bool isTerminalDurableSessionFailure(ApiException error) {
  return (error.statusCode == 400 || error.statusCode == 401) &&
      _terminalDurableSessionErrorCodes.contains(error.message);
}

enum AuthDiagnosticKind {
  refreshSuccess,
  refreshTransientFailure,
  refreshTerminalFailure,
  refreshReplayDetected,
  authorityGenerationMismatch,
}

class AuthDiagnosticEvent {
  const AuthDiagnosticEvent({
    required this.kind,
    required this.code,
    required this.sessionVersion,
    this.statusCode,
  });

  final AuthDiagnosticKind kind;
  final String code;
  final int sessionVersion;
  final int? statusCode;
}

typedef AuthDiagnosticSink = void Function(AuthDiagnosticEvent event);


class JiYiApiClient implements PhoneOneTapExchangeClient, SmsOtpGateway {
  JiYiApiClient({
    http.Client? httpClient,
    String? baseUrl,
    AuthSessionStore? sessionStore,
    AuthDiagnosticSink? authDiagnosticSink,
  })  : _http = httpClient ?? http.Client(),
        _sessionStore = sessionStore ?? SecureAuthSessionStore(),
        _authDiagnosticSink = authDiagnosticSink,
        baseUrl = _resolveApiBaseUrl(baseUrl);

  final http.Client _http;
  final AuthSessionStore _sessionStore;
  final AuthDiagnosticSink? _authDiagnosticSink;
  final String baseUrl;
  String? accessToken;
  String? _refreshToken;
  String? _sessionId;
  DateTime? _accessExpiresAt;
  // Authenticated user ID is never restored from local storage. It becomes
  // authoritative only after login/verification/refresh returns from the server.
  String? authenticatedUserId;
  int _sessionVersion = 0;
  int _unauthenticatedAuthGeneration = 0;
  Future<void>? _refreshInFlight;
  int? _refreshInFlightVersion;
  String? _refreshInFlightSessionId;
  String? _refreshInFlightCredential;
  Future<void> _sessionStoreTail = Future<void>.value();

  // 登录、注册和退出都会推进会话版本；后台同步用它检测账号切换。
  int get sessionVersion => _sessionVersion;

  /// Captures the current unauthenticated authentication attempt authority.
  ///
  /// One-tap login is allowed to establish a session only while this binding
  /// remains current. UI abandonment invalidates it before awaiting any native
  /// cleanup, so a late HTTP response cannot commit a session.
  int captureUnauthenticatedAuthGeneration() =>
      _unauthenticatedAuthGeneration;

  /// Invalidates every in-flight unauthenticated auth exchange.
  void invalidateUnauthenticatedAuthGeneration() {
    _unauthenticatedAuthGeneration += 1;
  }

  String? get authenticatedSessionId => _sessionId;

  @override
  Future<String> canonicalClientUuid() => _sessionStore.readOrCreateInstallationId();

  PushSessionBinding capturePushSession() {
    return PushSessionBinding._(_captureAuthenticatedSession());
  }

  void assertPushSessionCurrent(PushSessionBinding binding) {
    _assertAuthenticatedSessionCurrent(binding._snapshot);
  }

  bool get hasFreshAuthenticatedOwnerAuthority {
    final expiry = _accessExpiresAt;
    return accessToken != null &&
        _refreshToken != null &&
        _sessionId != null &&
        authenticatedUserId != null &&
        expiry != null &&
        expiry.isAfter(DateTime.now().toUtc());
  }

  /// Force a server round-trip to prove the durable session is still authoritative.
  /// CORE-001 can use this before publishing owner-bound background work.
  Future<void> revalidateAuthenticatedOwnerAuthority() => refreshCurrentSession();

  bool get showDevelopmentEndpoint => _appEnv != 'production';

  /// Cross-engine/process-safe local authority check for CORE-001 recovery.
  ///
  /// Background isolates never receive the refresh token from this method. They only learn
  /// whether the currently published session id still matches secure storage. Logout,
  /// logout-all, account switch and invalid-session cleanup remove/replace that binding.
  Future<bool> currentSessionMatchesSecureStorage() async {
    final sessionId = _sessionId;
    final owner = authenticatedUserId;
    if (sessionId == null || owner == null) return false;
    final persisted = await _sessionStore.readSession();
    return persisted != null && persisted.sessionId == sessionId;
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (accessToken != null) 'Authorization': 'Bearer $accessToken',
      };

  void _assertAuthenticatedSessionCurrent(_AuthenticatedSessionSnapshot snapshot) {
    if (_sessionVersion != snapshot.sessionVersion ||
        authenticatedUserId != snapshot.userId ||
        _sessionId != snapshot.sessionId) {
      _emitAuthDiagnostic(
        AuthDiagnosticKind.authorityGenerationMismatch,
        code: 'AUTHORITY_GENERATION_MISMATCH',
      );
      throw ProtocolException('登录状态已变化，请重试');
    }
  }

  _AuthenticatedSessionSnapshot _captureAuthenticatedSession() {
    final token = accessToken;
    final userId = authenticatedUserId;
    if (token == null ||
        token.trim().isEmpty ||
        userId == null ||
        userId.trim().isEmpty) {
      throw ApiException(401, '请先登录');
    }
    return _AuthenticatedSessionSnapshot(
      accessToken: token,
      userId: userId,
      sessionId: _sessionId,
      sessionVersion: _sessionVersion,
    );
  }

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  Future<Map<String, dynamic>> register({
    required String email,
    required String password,
    required String nickname,
    String timezone = 'Asia/Shanghai',
    String locale = 'zh-CN',
  }) {
    // Registration creates an unverified account only. No owner authority exists until
    // the email token is verified against the server.
    return _jsonRequest(
      'POST',
      '/auth/register',
      body: {
        'email': email.trim(),
        'password': password,
        'nickname': nickname.trim(),
        'timezone': timezone,
        'locale': locale,
      },
      authenticated: false,
    );
  }

  Future<Map<String, dynamic>> verifyEmail(String token) async {
    final installationId = await _sessionStore.readOrCreateInstallationId();
    final data = await _jsonRequest(
      'POST',
      '/auth/verify-email',
      body: {
        'token': token.trim(),
        'device_id': installationId,
        'client_platform': 'flutter',
      },
      authenticated: false,
    );
    final rawSession = data['session'];
    if (rawSession is Map<String, dynamic>) {
      await _establishAuthenticatedSession(rawSession);
    }
    return data;
  }

  Future<void> resendVerification(String email) async {
    await _jsonRequest(
      'POST',
      '/auth/resend-verification',
      body: {'email': email.trim()},
      authenticated: false,
    );
  }

  /// Reads the server-owned, provider-neutral pre-login capability contract.
  /// A caller must treat transport/protocol failure as unavailable for every
  /// non-email provider; this method never infers capability from local UI.
  Future<AuthCapabilities> fetchAuthCapabilities() async {
    final data = await _jsonRequest(
      'GET',
      '/auth/capabilities',
      authenticated: false,
    );
    return AuthCapabilities.fromJson(data);
  }

  Future<void> requestPasswordReset(String email) async {
    await _jsonRequest(
      'POST',
      '/auth/forgot-password',
      body: {'email': email.trim()},
      authenticated: false,
    );
  }

  Future<void> resetPassword({
    required String token,
    required String newPassword,
  }) async {
    await _jsonRequest(
      'POST',
      '/auth/reset-password',
      body: {
        'token': token.trim(),
        'new_password': newPassword,
      },
      authenticated: false,
    );
  }

  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    await _jsonRequest(
      'POST',
      '/auth/change-password',
      body: {
        'current_password': currentPassword,
        'new_password': newPassword,
      },
    );
    await _clearLocalSession();
  }

  Future<Map<String, dynamic>> login({
    required String email,
    required String password,
  }) async {
    final installationId = await _sessionStore.readOrCreateInstallationId();
    final data = await _jsonRequest(
      'POST',
      '/auth/login',
      body: {
        'email': email.trim(),
        'password': password,
        'device_id': installationId,
        'client_platform': 'flutter',
      },
      authenticated: false,
    );
    await _establishAuthenticatedSession(data);
    return data;
  }

  @override
  Future<void> exchangePhoneOneTap({
    required String loginToken,
    required String requestId,
    required String deviceId,
    String? clientPlatform,
    String? deviceName,
  }) async {
    if (loginToken.trim().isEmpty || requestId.trim().isEmpty) {
      throw ArgumentError('one-tap exchange requires an opaque token and request id');
    }
    final expectedSessionVersion = _sessionVersion;
    final expectedUnauthenticatedAuthGeneration =
        captureUnauthenticatedAuthGeneration();
    final data = await _jsonRequest(
      'POST',
      '/auth/phone/one-tap',
      body: {
        'login_token': loginToken,
        'request_id': requestId,
        'device_id': deviceId,
        if (clientPlatform != null) 'client_platform': clientPlatform,
        if (deviceName != null) 'device_name': deviceName,
      },
      authenticated: false,
    );
    await _establishAuthenticatedSession(
      data,
      expectedSessionVersion: expectedSessionVersion,
      expectedUnauthenticatedAuthGeneration:
          expectedUnauthenticatedAuthGeneration,
    );
  }

  @override
  Future<SmsOtpRequestResult> requestSmsOtp({required String phone}) async {
    final installationId = await _sessionStore.readOrCreateInstallationId();
    final data = await _jsonRequest(
      'POST',
      '/auth/phone/sms/request',
      body: {
        'phone': phone.trim(),
        'device_id': installationId,
        'client_platform': 'flutter',
      },
      authenticated: false,
    );
    return SmsOtpRequestResult.fromJson(data);
  }

  @override
  Future<void> verifySmsOtp({required String requestId, required String code}) async {
    if (requestId.trim().isEmpty || code.trim().length != 6) {
      throw ArgumentError('SMS OTP verification requires a request id and six-digit code');
    }
    final installationId = await _sessionStore.readOrCreateInstallationId();
    final expectedSessionVersion = _sessionVersion;
    final expectedUnauthenticatedAuthGeneration =
        captureUnauthenticatedAuthGeneration();
    final data = await _jsonRequest(
      'POST',
      '/auth/phone/sms/verify',
      body: {
        'request_id': requestId,
        'code': code.trim(),
        'device_id': installationId,
        'client_platform': 'flutter',
      },
      authenticated: false,
    );
    await _establishAuthenticatedSession(
      data,
      expectedSessionVersion: expectedSessionVersion,
      expectedUnauthenticatedAuthGeneration:
          expectedUnauthenticatedAuthGeneration,
    );
  }

  @override
  Future<void> cancel() async {
    invalidateUnauthenticatedAuthGeneration();
  }

  DateTime _requiredServerDateTime(
    Map<String, dynamic> data,
    String key,
  ) {
    final raw = data[key];
    if (raw is! String) {
      throw ProtocolException('认证服务返回格式不正确');
    }
    final parsed = DateTime.tryParse(raw);
    if (parsed == null || !parsed.isUtc) {
      throw ProtocolException('认证服务返回格式不正确');
    }
    return parsed;
  }

  Future<T> _runSessionStoreMutation<T>(
    Future<T> Function() operation,
  ) {
    final completer = Completer<T>();
    final previous = _sessionStoreTail;
    _sessionStoreTail = previous.then((_) async {
      try {
        completer.complete(await operation());
      } catch (error, stack) {
        completer.completeError(error, stack);
      }
    });
    return completer.future;
  }

  void _assertSessionGeneration(
    int? expectedSessionVersion, {
    String? expectedLocalSessionId,
    String? expectedLocalRefreshToken,
  }) {
    if ((expectedSessionVersion != null &&
            _sessionVersion != expectedSessionVersion) ||
        (expectedLocalSessionId != null &&
            _sessionId != expectedLocalSessionId) ||
        (expectedLocalRefreshToken != null &&
            _refreshToken != expectedLocalRefreshToken)) {
      _emitAuthDiagnostic(
        AuthDiagnosticKind.authorityGenerationMismatch,
        code: 'AUTHORITY_GENERATION_MISMATCH',
      );
      throw ProtocolException('登录状态已变化，请重试');
    }
  }

  void _assertUnauthenticatedAuthGeneration(int? expectedGeneration) {
    if (expectedGeneration != null &&
        _unauthenticatedAuthGeneration != expectedGeneration) {
      _emitAuthDiagnostic(
        AuthDiagnosticKind.authorityGenerationMismatch,
        code: 'UNAUTHENTICATED_AUTH_GENERATION_MISMATCH',
      );
      throw ProtocolException('登录操作已取消，请重试');
    }
  }

  void _emitAuthDiagnostic(
    AuthDiagnosticKind kind, {
    required String code,
    int? statusCode,
  }) {
    final event = AuthDiagnosticEvent(
      kind: kind,
      code: code,
      sessionVersion: _sessionVersion,
      statusCode: statusCode,
    );
    try {
      _authDiagnosticSink?.call(event);
    } catch (_) {
      // Diagnostic observers are never allowed to alter authentication semantics.
    }
    developer.log(
      'kind=${kind.name} code=$code status=${statusCode ?? '-'} generation=$_sessionVersion',
      name: 'jiyidashi.auth',
    );
  }

  Future<void> _establishAuthenticatedSession(
    Map<String, dynamic> data, {
    String? expectedSessionId,
    int? expectedSessionVersion,
    String? expectedLocalSessionId,
    String? expectedLocalRefreshToken,
    int? expectedUnauthenticatedAuthGeneration,
  }) async {
    final token = data['access_token'];
    final refresh = data['refresh_token'];
    final sessionId = data['session_id'];
    final userId = data['user_id'];
    if (token is! String ||
        token.trim().isEmpty ||
        refresh is! String ||
        refresh.trim().isEmpty ||
        sessionId is! String ||
        sessionId.trim().isEmpty ||
        userId is! String ||
        userId.trim().isEmpty ||
        (expectedSessionId != null && sessionId != expectedSessionId)) {
      throw ProtocolException('认证服务返回格式不正确');
    }
    final accessExpiresAt = _requiredServerDateTime(data, 'access_expires_at');

    // A refresh response is authoritative only for the local generation that
    // started it. Logout/account-switch must make any late response incapable
    // of writing refresh material back into Keychain/Keystore.
    _assertSessionGeneration(
      expectedSessionVersion,
      expectedLocalSessionId: expectedLocalSessionId,
      expectedLocalRefreshToken: expectedLocalRefreshToken,
    );
    _assertUnauthenticatedAuthGeneration(
      expectedUnauthenticatedAuthGeneration,
    );
    await _runSessionStoreMutation(() async {
      _assertSessionGeneration(
        expectedSessionVersion,
        expectedLocalSessionId: expectedLocalSessionId,
        expectedLocalRefreshToken: expectedLocalRefreshToken,
      );
      _assertUnauthenticatedAuthGeneration(
        expectedUnauthenticatedAuthGeneration,
      );
      await _sessionStore.writeSession(
        PersistedAuthSession(
          refreshToken: refresh,
          sessionId: sessionId,
        ),
      );
      try {
        _assertSessionGeneration(
          expectedSessionVersion,
          expectedLocalSessionId: expectedLocalSessionId,
          expectedLocalRefreshToken: expectedLocalRefreshToken,
        );
        _assertUnauthenticatedAuthGeneration(
          expectedUnauthenticatedAuthGeneration,
        );
      } catch (_) {
        // This runs inside the serialized mutation. No later legitimate
        // session write can race the cleanup of this stale candidate.
        try {
          await _sessionStore.clearSession();
        } catch (_) {
          // Preserve the authority failure; a stale session never becomes
          // in-memory authority even if secure-storage cleanup fails.
        }
        rethrow;
      }
    });
    _assertSessionGeneration(
      expectedSessionVersion,
      expectedLocalSessionId: expectedLocalSessionId,
      expectedLocalRefreshToken: expectedLocalRefreshToken,
    );
    _assertUnauthenticatedAuthGeneration(
      expectedUnauthenticatedAuthGeneration,
    );

    final sameOwnerSession =
        authenticatedUserId == userId && _sessionId == sessionId;
    accessToken = token;
    _refreshToken = refresh;
    _sessionId = sessionId;
    _accessExpiresAt = accessExpiresAt;
    authenticatedUserId = userId;
    if (!sameOwnerSession) {
      _sessionVersion += 1;
    }
  }

  Future<Map<String, dynamic>> _refreshWith(
    String refreshToken, {
    String? expectedSessionId,
    int? expectedSessionVersion,
    String? expectedLocalSessionId,
    String? expectedLocalRefreshToken,
  }) async {
    final data = await _jsonRequest(
      'POST',
      '/auth/refresh',
      body: {'refresh_token': refreshToken},
      authenticated: false,
    );
    await _establishAuthenticatedSession(
      data,
      expectedSessionId: expectedSessionId,
      expectedSessionVersion: expectedSessionVersion,
      expectedLocalSessionId: expectedLocalSessionId,
      expectedLocalRefreshToken: expectedLocalRefreshToken,
    );
    return data;
  }

  Future<void> _performBoundRefresh({
    required String refreshToken,
    required String sessionId,
    required int sessionVersion,
  }) async {
    try {
      await _refreshWith(
        refreshToken,
        expectedSessionId: sessionId,
        expectedSessionVersion: sessionVersion,
        expectedLocalSessionId: sessionId,
        expectedLocalRefreshToken: refreshToken,
      );
      _emitAuthDiagnostic(
        AuthDiagnosticKind.refreshSuccess,
        code: 'REFRESH_ROTATED',
      );
    } on ApiException catch (error) {
      final terminal = isTerminalDurableSessionFailure(error);
      _emitAuthDiagnostic(
        error.message == 'REFRESH_TOKEN_REUSED'
            ? AuthDiagnosticKind.refreshReplayDetected
            : (terminal
                ? AuthDiagnosticKind.refreshTerminalFailure
                : AuthDiagnosticKind.refreshTransientFailure),
        code: error.message,
        statusCode: error.statusCode,
      );
      if (terminal &&
          _sessionVersion == sessionVersion &&
          _sessionId == sessionId &&
          _refreshToken == refreshToken) {
        await _clearLocalSession();
      }
      rethrow;
    } on TransportException {
      _emitAuthDiagnostic(
        AuthDiagnosticKind.refreshTransientFailure,
        code: 'REFRESH_TRANSPORT_FAILURE',
      );
      rethrow;
    } on ProtocolException {
      _emitAuthDiagnostic(
        AuthDiagnosticKind.refreshTransientFailure,
        code: 'REFRESH_PROTOCOL_UNCERTAIN',
      );
      rethrow;
    }
  }

  Future<void> refreshCurrentSession() {
    final refresh = _refreshToken;
    final sessionId = _sessionId;
    final refreshVersion = _sessionVersion;
    if (refresh == null || sessionId == null) {
      return Future<void>.error(ApiException(401, '请先登录'));
    }
    final existing = _refreshInFlight;
    if (existing != null &&
        _refreshInFlightVersion == refreshVersion &&
        _refreshInFlightSessionId == sessionId &&
        _refreshInFlightCredential == refresh) {
      return existing;
    }

    late final Future<void> refreshFuture;
    refreshFuture = _performBoundRefresh(
      refreshToken: refresh,
      sessionId: sessionId,
      sessionVersion: refreshVersion,
    ).whenComplete(() {
      if (identical(_refreshInFlight, refreshFuture)) {
        _refreshInFlight = null;
        _refreshInFlightVersion = null;
        _refreshInFlightSessionId = null;
        _refreshInFlightCredential = null;
      }
    });
    _refreshInFlight = refreshFuture;
    _refreshInFlightVersion = refreshVersion;
    _refreshInFlightSessionId = sessionId;
    _refreshInFlightCredential = refresh;
    return refreshFuture;
  }

  Future<void> ensureFreshServerAuthority() async {
    final expiry = _accessExpiresAt;
    if (accessToken == null || authenticatedUserId == null || expiry == null) {
      throw ApiException(401, '请先登录');
    }
    if (expiry.isBefore(DateTime.now().toUtc().add(const Duration(minutes: 2)))) {
      await refreshCurrentSession();
    }
  }

  Future<AuthRestoreStatus> restorePersistedSession() async {
    final persisted = await _sessionStore.readSession();
    if (persisted == null) return AuthRestoreStatus.noPersistedSession;
    final restoreVersion = _sessionVersion;

    // Never publish locally cached owner identity. The server refresh response is the
    // only source allowed to reconstruct user_id/access authority after cold start.
    try {
      await _refreshWith(
        persisted.refreshToken,
        expectedSessionId: persisted.sessionId,
        expectedSessionVersion: restoreVersion,
      );
      _emitAuthDiagnostic(
        AuthDiagnosticKind.refreshSuccess,
        code: 'RESTORE_REFRESH_ROTATED',
      );
      return AuthRestoreStatus.restored;
    } on TransportException {
      _emitAuthDiagnostic(
        AuthDiagnosticKind.refreshTransientFailure,
        code: 'RESTORE_TRANSPORT_FAILURE',
      );
      return AuthRestoreStatus.serverUnavailable;
    } on ApiException catch (exc) {
      final terminal = isTerminalDurableSessionFailure(exc);
      _emitAuthDiagnostic(
        exc.message == 'REFRESH_TOKEN_REUSED'
            ? AuthDiagnosticKind.refreshReplayDetected
            : (terminal
                ? AuthDiagnosticKind.refreshTerminalFailure
                : AuthDiagnosticKind.refreshTransientFailure),
        code: exc.message,
        statusCode: exc.statusCode,
      );
      if (terminal) {
        if (_sessionVersion == restoreVersion) {
          await _clearLocalSession();
        }
        return AuthRestoreStatus.invalidSession;
      }
      // HTTP errors without an explicit durable-session terminal code are retryable.
      // In particular, validation/proxy/rate-limit uncertainty must never erase the
      // single-use refresh credential from secure storage.
      return AuthRestoreStatus.serverUnavailable;
    } on ProtocolException {
      _emitAuthDiagnostic(
        AuthDiagnosticKind.refreshTransientFailure,
        code: 'RESTORE_PROTOCOL_UNCERTAIN',
      );
      // A malformed/partial success response is authority uncertainty, not proof that the
      // durable server session is gone. Preserve Keychain/Keystore material for retry.
      return AuthRestoreStatus.serverUnavailable;
    }
  }

  Future<void> _clearLocalSession() async {
    accessToken = null;
    _refreshToken = null;
    _sessionId = null;
    _accessExpiresAt = null;
    authenticatedUserId = null;
    _sessionVersion += 1;
    await _runSessionStoreMutation(_sessionStore.clearSession);
  }

  Map<String, dynamic> _canonicalProfile(
    Map<String, dynamic> data,
    _AuthenticatedSessionSnapshot snapshot,
  ) {
    _assertAuthenticatedSessionCurrent(snapshot);
    final id = data['id'];
    if (id is! String || id != snapshot.userId) {
      throw ProtocolException('个人资料账号不匹配');
    }
    final elder = data['elder_mode_enabled'];
    return <String, dynamic>{
      ...data,
      // Malformed/missing preference fails closed to normal mode.
      'elder_mode_enabled': elder is bool ? elder : false,
    };
  }

  Future<Map<String, dynamic>> getProfile() async {
    final snapshot = _captureAuthenticatedSession();
    final data = await _jsonRequest('GET', '/user', authSnapshot: snapshot);
    return _canonicalProfile(data, snapshot);
  }

  Future<Map<String, dynamic>> updateElderMode(bool enabled) async {
    final snapshot = _captureAuthenticatedSession();
    final data = await _jsonRequest(
      'PATCH',
      '/user',
      body: {'elder_mode_enabled': enabled},
      authSnapshot: snapshot,
    );
    return _canonicalProfile(data, snapshot);
  }

  Future<Map<String, dynamic>> getTodayFootprint() async {
    // [人工注释][S2-012][S4-014] “今天”完全由服务端按账号 IANA timezone 决定；
    // read 绑定发起时认证会话，账号切换后 late response 必须 fail closed。
    final snapshot = _captureAuthenticatedSession();
    final data = await _jsonRequest(
      'GET',
      '/today/footprint',
      authSnapshot: snapshot,
    );
    _assertAuthenticatedSessionCurrent(snapshot);
    return data;
  }

  Future<Map<String, dynamic>> registerPushDevice({
    required String clientUuid,
    required String platform,
    required String provider,
    required String pushToken,
    String? appVersion,
    String? osVersion,
    PushSessionBinding? session,
  }) async {
    final binding = session ?? capturePushSession();
    final data = await _jsonRequest(
      'PUT',
      '/notifications/device',
      body: <String, dynamic>{
        'client_uuid': clientUuid,
        'platform': platform,
        'provider': provider,
        'push_token': pushToken,
        if (appVersion != null && appVersion.trim().isNotEmpty)
          'app_version': appVersion.trim(),
        if (osVersion != null && osVersion.trim().isNotEmpty)
          'os_version': osVersion.trim(),
      },
      authSnapshot: binding._snapshot,
    );
    _assertAuthenticatedSessionCurrent(binding._snapshot);
    final returnedClient = data['client_uuid'];
    if (returnedClient is! String || returnedClient != clientUuid) {
      throw ProtocolException('通知设备响应格式不正确');
    }
    if (data['push_enabled'] != true) {
      throw ProtocolException('通知设备未激活');
    }
    return data;
  }

  Future<Map<String, dynamic>> unregisterPushDevice({
    required String clientUuid,
    PushSessionBinding? session,
  }) async {
    final binding = session ?? capturePushSession();
    final encoded = Uri.encodeComponent(clientUuid);
    final data = await _jsonRequest(
      'DELETE',
      '/notifications/device/$encoded',
      authSnapshot: binding._snapshot,
    );
    _assertAuthenticatedSessionCurrent(binding._snapshot);
    final returnedClient = data['client_uuid'];
    if (returnedClient is! String || returnedClient != clientUuid) {
      throw ProtocolException('通知设备响应格式不正确');
    }
    if (data['push_enabled'] == true) {
      throw ProtocolException('通知设备注销未生效');
    }
    return data;
  }

  AccountDeleteSessionBinding captureAccountDeleteSession() {
    return AccountDeleteSessionBinding._(_captureAuthenticatedSession());
  }

  void assertAccountDeleteSessionCurrent(AccountDeleteSessionBinding binding) {
    _assertAuthenticatedSessionCurrent(binding._snapshot);
  }

  Future<Map<String, dynamic>> deleteAccount({
    required String requestId,
    required bool localCleanupReady,
    AccountDeleteSessionBinding? session,
  }) async {
    final normalized = requestId.trim();
    if (normalized.isEmpty) {
      throw ArgumentError.value(requestId, 'requestId', 'request ID must not be empty');
    }
    final snapshot = session?._snapshot ?? _captureAuthenticatedSession();

    // SEC-014/P1-1: the complete PREPARE → local purge → COMMIT transaction
    // is bound to the session captured before confirmation opened. Never recapture
    // the currently logged-in account for a later phase of the same destructive intent.
    _assertAuthenticatedSessionCurrent(snapshot);
    final data = await _jsonRequest(
      'POST',
      '/account/delete',
      body: {
        'request_id': normalized,
        'confirmation': 'DELETE_MY_ACCOUNT',
        'local_cleanup_ready': localCleanupReady,
      },
      authSnapshot: snapshot,
    );
    _assertAuthenticatedSessionCurrent(snapshot);
    return data;
  }

  Future<Map<String, dynamic>> updateProfile({
    required String nickname,
    required String timezone,
    String locale = 'zh-CN',
  }) {
    // [人工注释][S1-002] 时区修改只提交 IANA 名称，服务端再次校验后才影响自然日边界。
    return _jsonRequest(
      'PATCH',
      '/user',
      body: {
        'nickname': nickname.trim(),
        'timezone': timezone.trim(),
        'locale': locale.trim(),
      },
    );
  }

  Future<Map<String, dynamic>> createTextMemory({
    String? title,
    required String content,
    DateTime? occurredAt,
    String? clientUuid,
  }) {
    // [人工注释][S1-003] 客户端只声明 USER_TEXT capture_source，可信等级继续由服务端决定。
    // outbox 首次在线尝试携带稳定 UUID 与冻结的发生时间，response-loss 重试必须复用二者。
    return _jsonRequest(
      'POST',
      '/memories',
      body: {
        'memory_type': 'NOTE',
        if (title != null && title.trim().isNotEmpty) 'title': title.trim(),
        'content': content.trim(),
        if (occurredAt != null) 'occurred_at': occurredAt.toUtc().toIso8601String(),
        'capture_source': 'USER_TEXT',
      },
      extraHeaders: clientUuid == null
          ? null
          : {'Idempotency-Key': clientUuid.trim()},
    );
  }

  Future<MediaUploadSession> createMediaUpload({
    required String clientUploadId,
    required String kind,
    required String contentType,
    required int sizeBytes,
    String? originalFilename,
  }) async {
    final data = await _jsonRequest(
      'POST',
      '/media/uploads',
      body: {
        'client_upload_id': clientUploadId,
        'kind': kind,
        'content_type': contentType,
        'size_bytes': sizeBytes,
        if (originalFilename != null && originalFilename.trim().isNotEmpty)
          'original_filename': originalFilename.trim(),
      },
    );
    return MediaUploadSession.fromJson(data);
  }

  Future<void> uploadSignedMedia(
    SignedUploadTarget target,
    List<int> bytes,
  ) async {
    // Signed PUT 是对象存储临时能力票据，不能附带迹忆 Authorization。
    // 只发送服务端签发的 headers，避免把账号 token 泄露给 storage host。
    if (target.method != 'PUT') {
      throw ProtocolException('媒体上传协议不正确');
    }
    late final http.Response response;
    try {
      response = await _http.put(target.url, headers: target.headers, body: bytes);
    } on http.ClientException catch (exc) {
      throw TransportException('媒体上传连接失败', exc);
    } on TimeoutException catch (exc) {
      throw TransportException('媒体上传超时', exc);
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(response.statusCode, '媒体上传失败');
    }
  }

  Future<Uint8List> downloadSignedMedia(
    SignedDownloadTarget target, {
    int maxBytes = 50 * 1024 * 1024,
  }) async {
    if (target.method != 'GET') {
      throw ProtocolException('媒体下载协议不正确');
    }
    if (maxBytes <= 0) {
      throw ArgumentError.value(maxBytes, 'maxBytes', 'must be positive');
    }

    final request = http.Request('GET', target.url)
      ..headers.addAll(target.headers);
    late final http.StreamedResponse response;
    try {
      response = await _http
          .send(request)
          .timeout(const Duration(seconds: 30));
    } on http.ClientException catch (exc) {
      throw TransportException('媒体下载连接失败', exc);
    } on TimeoutException catch (exc) {
      throw TransportException('媒体下载超时', exc);
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(response.statusCode, '媒体下载失败');
    }

    final bytes = BytesBuilder(copy: false);
    var received = 0;
    try {
      await for (final chunk
          in response.stream.timeout(const Duration(seconds: 30))) {
        received += chunk.length;
        if (received > maxBytes) {
          throw ProtocolException('媒体下载超过本地缓存上限');
        }
        bytes.add(chunk);
      }
    } on TimeoutException catch (exc) {
      throw TransportException('媒体下载超时', exc);
    }
    if (received == 0) {
      throw ProtocolException('媒体下载为空');
    }
    return bytes.takeBytes();
  }

  Future<Map<String, dynamic>> completeMediaUpload(String mediaId) {
    return _jsonRequest('POST', '/media/$mediaId/complete');
  }

  Future<MediaDownloadSession> createMediaDownload(String mediaId) async {
    final normalized = mediaId.trim();
    if (normalized.isEmpty) {
      throw ArgumentError.value(mediaId, 'mediaId', 'media ID must not be empty');
    }
    // Signed object URLs are temporary capabilities. Bind signing to the exact authenticated
    // session that started the request so an owner switch cannot publish a late owner-A URL.
    final snapshot = _captureAuthenticatedSession();
    final data = await _jsonRequest(
      'POST',
      '/media/$normalized/download',
      authSnapshot: snapshot,
    );
    _assertAuthenticatedSessionCurrent(snapshot);
    final returnedId = data['media_id'];
    final cacheVersion = data['cache_version'];
    final rawDownload = data['download'];
    final validCacheVersion = cacheVersion is String &&
        cacheVersion.length == 64 &&
        cacheVersion.codeUnits.every((unit) =>
            (unit >= 48 && unit <= 57) || (unit >= 97 && unit <= 102));
    if (returnedId is! String ||
        returnedId.toLowerCase() != normalized.toLowerCase() ||
        !validCacheVersion ||
        rawDownload is! Map<String, dynamic>) {
      throw ProtocolException('服务端返回格式不正确');
    }
    return MediaDownloadSession(
      mediaId: returnedId,
      cacheVersion: cacheVersion,
      download: SignedDownloadTarget.fromJson(rawDownload),
    );
  }

  Future<Map<String, dynamic>> createPhotoMemory({
    required String mediaId,
    String? title,
    required String content,
    DateTime? occurredAt,
  }) {
    return _jsonRequest(
      'POST',
      '/media/$mediaId/memory',
      body: {
        if (title != null && title.trim().isNotEmpty) 'title': title.trim(),
        'content': content.trim(),
        if (occurredAt != null) 'occurred_at': occurredAt.toUtc().toIso8601String(),
      },
    );
  }

  Future<Map<String, dynamic>> createVoiceMemory({
    required String mediaId,
    String? title,
    DateTime? occurredAt,
  }) {
    return _jsonRequest(
      'POST',
      '/media/$mediaId/voice-memory',
      body: {
        if (title != null && title.trim().isNotEmpty) 'title': title.trim(),
        if (occurredAt != null) 'occurred_at': occurredAt.toUtc().toIso8601String(),
      },
    );
  }

  Future<Map<String, dynamic>> getMemory(String memoryId) {
    return _jsonRequest('GET', '/memories/$memoryId');
  }

  Future<Map<String, dynamic>> updateMemory(
    String memoryId, {
    required int expectedRevision,
    String? title,
    required String content,
  }) {
    final normalizedTitle = title?.trim() ?? '';
    final normalizedContent = content.trim();
    if (normalizedContent.isEmpty) {
      throw ArgumentError.value(
        content,
        'content',
        'memory content must not be empty',
      );
    }
    // Stage 1 编辑只提交用户可见 title/content；可信字段、来源和发生时间继续由服务端所有。
    return _jsonRequest(
      'PATCH',
      '/memories/$memoryId',
      body: {
        'expected_revision': expectedRevision,
        'title': normalizedTitle.isEmpty ? null : normalizedTitle,
        'content': normalizedContent,
      },
    );
  }

  Future<void> deleteMemory(String memoryId) async {
    // [人工注释][S1-019] 删除只调用服务端 soft-delete 入口；客户端删除后不得保留本地“可回答”状态。
    await _jsonRequest('DELETE', '/memories/$memoryId');
  }

  Future<Map<String, dynamic>> createReminder({
    required String memoryId,
    required String title,
    String? content,
    required DateTime remindAt,
    required String clientUuid,
  }) {
    final normalizedTitle = title.trim();
    if (normalizedTitle.isEmpty) {
      throw ArgumentError.value(title, 'title', 'reminder title must not be empty');
    }
    final normalizedContent = content?.trim() ?? '';
    // [人工注释][S1-025] Flutter 总是把设备上选定的绝对时刻转换成 UTC/Z；
    // 后端仍拒绝任何没有 offset 的 naive 时间，不在服务器猜用户时区。
    return _jsonRequest(
      'POST',
      '/reminders',
      body: {
        'memory_id': memoryId,
        'title': normalizedTitle,
        if (normalizedContent.isNotEmpty) 'content': normalizedContent,
        'remind_at': remindAt.toUtc().toIso8601String(),
      },
      // [人工注释][S1-025] 同一次 Reminder create 的 transport/response-loss 重试必须复用此 UUID。
      extraHeaders: {'Idempotency-Key': clientUuid.trim()},
    );
  }

  Future<List<Map<String, dynamic>>> listReminders({
    String? status,
    int limit = 100,
  }) {
    final normalized = status?.trim();
    final query = <String, String>{'limit': limit.toString()};
    if (normalized != null && normalized.isNotEmpty) {
      query['status'] = normalized;
    }
    return _jsonListRequest(
      Uri(path: '/reminders', queryParameters: query).toString(),
    );
  }

  Future<Map<String, dynamic>> completeReminder(String reminderId) {
    return _jsonRequest('POST', '/reminders/$reminderId/done');
  }

  Future<Map<String, dynamic>> cancelReminder(String reminderId) {
    return _jsonRequest('POST', '/reminders/$reminderId/cancel');
  }

  Future<Map<String, dynamic>> rememberObjectLocation({
    required String objectName,
    required String locationText,
    DateTime? recordedAt,
    String? clientUuid,
  }) async {
    // [人工注释][S1-009] “东西在哪”先建立/复用 Object，再写入有 Evidence 的 ObjectLocation。
    // 两段 HTTP 属于同一个逻辑 mutation，必须固定使用开始时捕获的认证快照。
    final authSnapshot = _captureAuthenticatedSession();
    final object = await _jsonRequest(
      'POST',
      '/objects',
      body: {'name': objectName.trim()},
      authSnapshot: authSnapshot,
    );
    final objectId = object['id'];
    if (objectId is! String || objectId.trim().isEmpty) {
      throw ProtocolException('服务端返回格式不正确');
    }
    return _jsonRequest(
      'POST',
      '/objects/$objectId/locations',
      body: {
        'location_text': locationText.trim(),
        if (recordedAt != null) 'recorded_at': recordedAt.toUtc().toIso8601String(),
        'capture_source': 'USER_TEXT',
      },
      extraHeaders: clientUuid == null
          ? null
          : {'Idempotency-Key': clientUuid.trim()},
      authSnapshot: authSnapshot,
    );
  }

  Future<Map<String, dynamic>> markObjectLocationStale(String objectName) async {
    // [人工注释][S1-011] 失效操作先从用户自己的 Object 列表精确定位对象，
    // 不通过 POST 创建一个原本不存在的空对象。
    final objects = await _jsonListRequest('/objects');
    final normalized = objectName.trim().toLowerCase();
    Map<String, dynamic>? matched;
    for (final object in objects) {
      if ((object['name']?.toString().trim().toLowerCase() ?? '') == normalized) {
        matched = object;
        break;
      }
    }
    if (matched == null) {
      throw ApiException(404, '没有找到这个物品');
    }
    return _jsonRequest('POST', '/objects/${matched['id']}/location/stale');
  }

  Future<LocationBatchResult> uploadLocationBatch(
    List<LocationUploadPoint> points,
  ) async {
    if (points.isEmpty || points.length > 500) {
      throw ArgumentError.value(
        points.length,
        'points',
        'location batch must contain 1..500 points',
      );
    }
    // P consumes the already-merged S2-006 contract verbatim. Stable client_uuid lives
    // inside each point; no second idempotency header/protocol is invented here.
    final data = await _jsonRequest(
      'POST',
      '/location/batch',
      body: {
        'points': points.map((point) => point.toJson()).toList(growable: false),
      },
    );
    return LocationBatchResult.fromJson(data);
  }

  Future<Map<String, dynamic>> getTimelineEvents({
    int limit = 30,
    String? cursor,
    String? day,
  }) {
    if (limit < 1 || limit > 100) {
      throw ArgumentError.value(limit, 'limit', 'timeline limit must be 1..100');
    }
    final query = <String, String>{'limit': limit.toString()};
    final normalizedCursor = cursor?.trim();
    if (normalizedCursor != null && normalizedCursor.isNotEmpty) {
      query['cursor'] = normalizedCursor;
    }
    final normalizedDay = day?.trim();
    if (normalizedDay != null && normalizedDay.isNotEmpty) {
      if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(normalizedDay)) {
        throw ArgumentError.value(
          day,
          'day',
          'timeline day must be YYYY-MM-DD',
        );
      }
      query['day'] = normalizedDay;
    }
    return _jsonRequest(
      'GET',
      Uri(
        path: '/timeline/events',
        queryParameters: query,
      ).toString(),
    );
  }

  Future<List<Map<String, dynamic>>> listPlaces({int limit = 100}) {
    if (limit < 1 || limit > 500) {
      throw ArgumentError.value(limit, 'limit', 'place limit must be 1..500');
    }
    return _jsonListRequest(
      Uri(
        path: '/location/places',
        queryParameters: {'limit': limit.toString()},
      ).toString(),
    );
  }

  Future<Map<String, dynamic>> getPlaceDetail(
    String placeId, {
    int limit = 50,
    String? cursor,
  }) {
    final normalized = placeId.trim();
    if (normalized.isEmpty) {
      throw ArgumentError.value(placeId, 'placeId', 'place ID must not be empty');
    }
    if (limit < 1 || limit > 200) {
      throw ArgumentError.value(limit, 'limit', 'visit limit must be 1..200');
    }
    final query = <String, String>{'limit': limit.toString()};
    final normalizedCursor = cursor?.trim();
    if (normalizedCursor != null && normalizedCursor.isNotEmpty) {
      query['cursor'] = normalizedCursor;
    }
    return _jsonRequest(
      'GET',
      Uri(
        path: '/location/places/$normalized',
        queryParameters: query,
      ).toString(),
    );
  }

  Future<Map<String, dynamic>> getRecordingHealth({
    Map<String, dynamic>? clientState,
  }) async {
    // CORE-003 reads are bound to the exact authenticated session that started the request.
    // A late owner-A response after login as owner B must never repopulate the health surface.
    final snapshot = _captureAuthenticatedSession();
    final data = await _jsonRequest(
      clientState == null ? 'GET' : 'POST',
      '/recording/health',
      body: clientState,
      authSnapshot: snapshot,
    );
    _assertAuthenticatedSessionCurrent(snapshot);
    return data;
  }

  Future<Map<String, dynamic>> getPrivacyStatus() {
    return _jsonRequest('GET', '/privacy/status');
  }

  Future<Map<String, dynamic>> pauseMemory(int minutes) {
    // [人工注释][S1-023] 客户端只选择暂停时长，历史 pause interval 仍由服务端持久化。
    return _jsonRequest(
      'POST',
      '/privacy/pause',
      body: {'duration_minutes': minutes},
    );
  }

  Future<Map<String, dynamic>> pauseMemoryToday() {
    // [人工注释][S1-023] “今天”由服务端按用户 IANA timezone 计算本地午夜。
    return _jsonRequest('POST', '/privacy/pause/today');
  }

  Future<Map<String, dynamic>> resumeMemory() {
    // [人工注释][S1-024] 恢复只结束当前暂停，服务端仍保留历史暂停区间阻断延迟补传。
    return _jsonRequest('POST', '/privacy/resume');
  }

  Future<Map<String, dynamic>> queryMemory(String question) async {
    // [人工注释][S1-013][S4-013] 查询绑定发起时的认证会话；malformed 2xx 必须 fail closed。
    final snapshot = _captureAuthenticatedSession();
    final raw = await _jsonRequest(
      'POST',
      '/memory/query',
      body: {'question': question.trim()},
      authSnapshot: snapshot,
    );
    _assertAuthenticatedSessionCurrent(snapshot);
    return _parseMemoryQueryResult(raw);
  }

  Future<_AuthenticatedSessionSnapshot> _refreshForRevocation(
    String refreshToken,
    _AuthenticatedSessionSnapshot original,
  ) async {
    final decoded = _decodeResponse(
      await _sendRequestOnce(
        'POST',
        '/auth/refresh',
        body: {'refresh_token': refreshToken},
        authenticated: false,
      ),
    );
    if (decoded is! Map<String, dynamic>) {
      throw ProtocolException('认证服务返回格式不正确');
    }
    final token = decoded['access_token'];
    final sessionId = decoded['session_id'];
    final userId = decoded['user_id'];
    if (token is! String ||
        token.trim().isEmpty ||
        sessionId is! String ||
        sessionId != original.sessionId ||
        userId is! String ||
        userId != original.userId) {
      throw ProtocolException('认证服务返回格式不正确');
    }
    // Never persist or publish this rotated credential. It exists only long enough
    // to complete the explicit revoke requested by the user.
    return _AuthenticatedSessionSnapshot(
      accessToken: token,
      userId: userId,
      sessionId: sessionId,
      sessionVersion: original.sessionVersion,
    );
  }

  Future<void> _revokeAfterLocalLogout(
    String path, {
    required _AuthenticatedSessionSnapshot snapshot,
    required String? refreshToken,
  }) async {
    var revokeSnapshot = snapshot;
    var response = await _sendRequestOnce(
      'POST',
      path,
      authenticated: true,
      authSnapshot: revokeSnapshot,
    );
    if (response.statusCode == 401 &&
        _responseErrorDetail(response) == 'INVALID_ACCESS_TOKEN' &&
        refreshToken != null &&
        refreshToken.trim().isNotEmpty) {
      revokeSnapshot = await _refreshForRevocation(refreshToken, snapshot);
      response = await _sendRequestOnce(
        'POST',
        path,
        authenticated: true,
        authSnapshot: revokeSnapshot,
      );
    }
    _decodeResponse(response);
  }

  Future<void> logout() async {
    final snapshot = accessToken != null &&
            authenticatedUserId != null &&
            _sessionId != null
        ? _captureAuthenticatedSession()
        : null;
    final refreshForRevocation = _refreshToken;
    // _clearLocalSession mutates memory before its first await. This preserves the
    // synchronous stale-session boundary while keeping the captured refresh secret
    // only on this stack for an expired-access revoke fallback.
    final clearFuture = _clearLocalSession();
    try {
      if (snapshot != null) {
        await _revokeAfterLocalLogout(
          '/auth/logout',
          snapshot: snapshot,
          refreshToken: refreshForRevocation,
        );
      }
    } on TransportException {
      // Local authority remains fail-closed when the server is unreachable.
    } on ApiException catch (error) {
      if (error.statusCode >= 500) rethrow;
      // 4xx here means the captured server session/refresh authority is no longer
      // usable; never resurrect local state after explicit logout intent.
    } finally {
      await clearFuture;
    }
  }

  Future<void> logoutAll() async {
    final snapshot = _captureAuthenticatedSession();
    final refreshForRevocation = _refreshToken;
    final clearFuture = _clearLocalSession();
    try {
      await _revokeAfterLocalLogout(
        '/auth/logout-all',
        snapshot: snapshot,
        refreshToken: refreshForRevocation,
      );
    } on TransportException {
      // Fail local state closed even when the network is unavailable.
    } finally {
      await clearFuture;
    }
  }
  // #163 Flutter V2 reuses the existing authenticated-session snapshot.
  // V2 operations are never silently added to the existing offline queue.
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final snapshot = _captureAuthenticatedSession();
    final decoded = _decodeResponse(
      await _request(
        method,
        path,
        body: body,
        authSnapshot: snapshot,
      ),
    );
    _assertAuthenticatedSessionCurrent(snapshot);
    return decoded;
  }


  // [人工注释][S1-019] 统一传输层显式支持 DELETE；204 空响应也必须沿同一服务端成功链处理，
  // 不能让删除退化成客户端本地隐藏。
  String? _responseErrorDetail(http.Response response) {
    if (response.body.isEmpty) return null;
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map<String, dynamic>) {
        return decoded['detail']?.toString();
      }
    } on FormatException {
      return null;
    }
    return null;
  }

  Future<http.Response> _sendRequestOnce(
    String method,
    String path, {
    Map<String, dynamic>? body,
    required bool authenticated,
    Map<String, String>? extraHeaders,
    _AuthenticatedSessionSnapshot? authSnapshot,
  }) async {
    final token = authSnapshot?.accessToken ?? accessToken;
    if (authenticated && (token == null || token.trim().isEmpty)) {
      throw ApiException(401, '请先登录');
    }
    final headers = <String, String>{
      ...(authenticated
          ? (authSnapshot == null
              ? _headers
              : {
                  'Content-Type': 'application/json',
                  'Authorization': 'Bearer ${authSnapshot.accessToken}',
                })
          : const {'Content-Type': 'application/json'}),
      ...?extraHeaders,
    };
    final encoded = body == null ? null : jsonEncode(body);
    try {
      return switch (method) {
        'GET' => await _http.get(_uri(path), headers: headers),
        'POST' => await _http.post(_uri(path), headers: headers, body: encoded),
        'PATCH' => await _http.patch(_uri(path), headers: headers, body: encoded),
        'PUT' => await _http.put(_uri(path), headers: headers, body: encoded),
        'DELETE' => await _http.delete(_uri(path), headers: headers, body: encoded),
        _ => throw ArgumentError('Unsupported method: $method'),
      };
    } on http.ClientException catch (exc) {
      throw TransportException('网络连接失败', exc);
    } on TimeoutException catch (exc) {
      throw TransportException('网络请求超时', exc);
    }
  }

  // [AUTH-001] Ordinary authenticated requests get exactly one transparent access-token
  // refresh. Exact-session snapshot operations intentionally do not auto-rotate.
  Future<http.Response> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
    bool authenticated = true,
    Map<String, String>? extraHeaders,
    _AuthenticatedSessionSnapshot? authSnapshot,
  }) async {
    var response = await _sendRequestOnce(
      method,
      path,
      body: body,
      authenticated: authenticated,
      extraHeaders: extraHeaders,
      authSnapshot: authSnapshot,
    );
    if (!authenticated || response.statusCode != 401) {
      return response;
    }

    final detail = _responseErrorDetail(response);
    if (detail == 'AUTH_SESSION_INVALID' || detail == 'AUTH_ACCOUNT_UNAVAILABLE') {
      await _clearLocalSession();
      return response;
    }
    if (detail != 'INVALID_ACCESS_TOKEN' ||
        _refreshToken == null ||
        _sessionId == null) {
      return response;
    }

    if (authSnapshot != null) {
      _assertAuthenticatedSessionCurrent(authSnapshot);
    }
    await refreshCurrentSession();
    if (authSnapshot != null) {
      _assertAuthenticatedSessionCurrent(authSnapshot);
    }
    final retrySnapshot =
        authSnapshot == null ? null : _captureAuthenticatedSession();
    response = await _sendRequestOnce(
      method,
      path,
      body: body,
      authenticated: true,
      extraHeaders: extraHeaders,
      authSnapshot: retrySnapshot,
    );
    return response;
  }

  // [人工注释][S1-019][S1-016] 204 空响应仍合法；非 2xx 即使 body 为 HTML/坏 JSON 也属于服务端失败，只有 2xx 坏 JSON 才是协议异常。
  dynamic _decodeResponse(http.Response response) {
    final isError = response.statusCode < 200 || response.statusCode >= 300;
    dynamic decoded;
    if (response.body.isEmpty) {
      decoded = <String, dynamic>{};
    } else {
      try {
        decoded = jsonDecode(response.body);
      } on FormatException catch (exc) {
        if (isError) throw ApiException(response.statusCode, '请求失败');
        throw ProtocolException('服务端返回格式不正确', exc);
      }
    }
    if (isError) {
      final detail = decoded is Map<String, dynamic> ? decoded['detail'] : null;
      throw ApiException(response.statusCode, detail?.toString() ?? '请求失败');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> _jsonRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
    bool authenticated = true,
    Map<String, String>? extraHeaders,
    _AuthenticatedSessionSnapshot? authSnapshot,
  }) async {
    final decoded = _decodeResponse(
      await _request(
        method,
        path,
        body: body,
        authenticated: authenticated,
        extraHeaders: extraHeaders,
        authSnapshot: authSnapshot,
      ),
    );
    if (decoded is! Map<String, dynamic>) {
      // [人工注释][S1-016] 2xx 结构异常是协议失败，不是 transport。
      throw ProtocolException('服务端返回格式不正确');
    }
    return decoded;
  }

  // [人工注释][S1-011] 物品失效前必须读取用户真实 Object 列表；这个 helper 只解析服务端列表，
  // 不创建、猜测或补造 Object。
  Future<List<Map<String, dynamic>>> _jsonListRequest(String path) async {
    final decoded = _decodeResponse(await _request('GET', path));
    if (decoded is! List<dynamic>) {
      // [人工注释][S1-016] 列表结构异常同样 fail closed，不允许降级为 offline。
      throw ProtocolException('服务端返回格式不正确');
    }
    return decoded.map((item) {
      if (item is! Map<String, dynamic>) {
        throw ProtocolException('服务端返回格式不正确');
      }
      return item;
    }).toList();
  }
}
