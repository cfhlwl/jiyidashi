import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'auth_session_store.dart';

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
    required this.sessionVersion,
  });

  final String accessToken;
  final String userId;
  final int sessionVersion;
}

class AccountDeleteSessionBinding {
  const AccountDeleteSessionBinding._(this._snapshot);

  final _AuthenticatedSessionSnapshot _snapshot;

  String get ownerUserId => _snapshot.userId;
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

Map<String, dynamic> _parseMemoryQueryResult(Map<String, dynamic> data) {
  final answer = data['answer'];
  final canAnswer = data['can_answer'];
  final certainty = data['certainty'];
  final reason = data['reason'];
  final intent = data['intent'];
  final evidence = data['evidence'];
  final memoryIds = data['memory_ids'];
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
  });

  final canonicalAnswer =
      canAnswer == true &&
      answer is String &&
      answer.trim().isNotEmpty &&
      (certainty == 'confirmed' || certainty == 'evidence') &&
      parsedEvidence.isNotEmpty &&
      parsedIds.isNotEmpty;
  final canonicalNoEvidence =
      canAnswer == false &&
      answer == null &&
      certainty == 'unknown' &&
      parsedEvidence.isEmpty &&
      parsedIds.isEmpty;
  if (!canonicalAnswer && !canonicalNoEvidence) {
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


class JiYiApiClient {
  JiYiApiClient({
    http.Client? httpClient,
    String? baseUrl,
    AuthSessionStore? sessionStore,
  })  : _http = httpClient ?? http.Client(),
        _sessionStore = sessionStore ?? SecureAuthSessionStore(),
        baseUrl = _resolveApiBaseUrl(baseUrl);

  final http.Client _http;
  final AuthSessionStore _sessionStore;
  final String baseUrl;
  String? accessToken;
  String? _refreshToken;
  String? _sessionId;
  DateTime? _accessExpiresAt;
  // Authenticated user ID is never restored from local storage. It becomes
  // authoritative only after login/verification/refresh returns from the server.
  String? authenticatedUserId;
  int _sessionVersion = 0;
  Future<void>? _refreshInFlight;

  // 登录、注册和退出都会推进会话版本；后台同步用它检测账号切换。
  int get sessionVersion => _sessionVersion;

  String? get authenticatedSessionId => _sessionId;

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

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (accessToken != null) 'Authorization': 'Bearer $accessToken',
      };

  void _assertAuthenticatedSessionCurrent(_AuthenticatedSessionSnapshot snapshot) {
    if (_sessionVersion != snapshot.sessionVersion ||
        accessToken != snapshot.accessToken ||
        authenticatedUserId != snapshot.userId) {
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

  Future<void> _establishAuthenticatedSession(
    Map<String, dynamic> data, {
    String? expectedSessionId,
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

    // Secure persistence succeeds before in-memory owner authority is published.
    await _sessionStore.writeSession(
      PersistedAuthSession(
        refreshToken: refresh,
        sessionId: sessionId,
      ),
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
    );
    return data;
  }

  Future<void> refreshCurrentSession() async {
    final refresh = _refreshToken;
    final sessionId = _sessionId;
    if (refresh == null || sessionId == null) {
      throw ApiException(401, '请先登录');
    }
    final existing = _refreshInFlight;
    if (existing != null) return existing;

    final completer = Completer<void>();
    _refreshInFlight = completer.future;
    try {
      await _refreshWith(refresh, expectedSessionId: sessionId);
      completer.complete();
    } on ApiException catch (error, stack) {
      if (error.statusCode == 400 || error.statusCode == 401) {
        await _clearLocalSession();
      }
      completer.completeError(error, stack);
      rethrow;
    } catch (error, stack) {
      completer.completeError(error, stack);
      rethrow;
    } finally {
      _refreshInFlight = null;
    }
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

    // Never publish locally cached owner identity. The server refresh response is the
    // only source allowed to reconstruct user_id/access authority after cold start.
    try {
      await _refreshWith(
        persisted.refreshToken,
        expectedSessionId: persisted.sessionId,
      );
      return AuthRestoreStatus.restored;
    } on TransportException {
      return AuthRestoreStatus.serverUnavailable;
    } on ApiException catch (exc) {
      if (exc.statusCode == 400 || exc.statusCode == 401) {
        await _clearLocalSession();
        return AuthRestoreStatus.invalidSession;
      }
      return AuthRestoreStatus.serverUnavailable;
    } on ProtocolException {
      await _clearLocalSession();
      return AuthRestoreStatus.invalidSession;
    }
  }

  Future<void> _clearLocalSession() async {
    accessToken = null;
    _refreshToken = null;
    _sessionId = null;
    _accessExpiresAt = null;
    authenticatedUserId = null;
    _sessionVersion += 1;
    await _sessionStore.clearSession();
  }

  Map<String, dynamic> _canonicalProfile(
    Map<String, dynamic> data,
    _AuthenticatedSessionSnapshot snapshot,
  ) {
    if (_sessionVersion != snapshot.sessionVersion ||
        accessToken != snapshot.accessToken ||
        authenticatedUserId != snapshot.userId) {
      throw ProtocolException('登录状态已变化，请重试');
    }
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

  Future<Map<String, dynamic>> completeMediaUpload(String mediaId) {
    return _jsonRequest('POST', '/media/$mediaId/complete');
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

  Future<void> logout() async {
    try {
      if (accessToken != null && authenticatedUserId != null) {
        await _jsonRequest('POST', '/auth/logout');
      }
    } finally {
      // User intent always removes local owner authority and secure refresh material.
      await _clearLocalSession();
    }
  }

  Future<void> logoutAll() async {
    try {
      await _jsonRequest('POST', '/auth/logout-all');
    } finally {
      await _clearLocalSession();
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
    if (!authenticated || authSnapshot != null || response.statusCode != 401) {
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

    await refreshCurrentSession();
    response = await _sendRequestOnce(
      method,
      path,
      body: body,
      authenticated: true,
      extraHeaders: extraHeaders,
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
