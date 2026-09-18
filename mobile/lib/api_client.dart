import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

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

class JiYiApiClient {
  JiYiApiClient({http.Client? httpClient, String? baseUrl})
      : _http = httpClient ?? http.Client(),
        baseUrl = _resolveApiBaseUrl(baseUrl);

  final http.Client _http;
  final String baseUrl;
  String? accessToken;
  // [人工注释][S1-015] 登录态同时保留服务端签发的 user_id，作为本机 SQLite 数据的账号隔离键；不得用昵称/邮箱猜身份。
  String? authenticatedUserId;
  int _sessionVersion = 0;

  // 登录、注册和退出都会推进会话版本；后台同步用它检测账号切换。
  int get sessionVersion => _sessionVersion;

  bool get showDevelopmentEndpoint => _appEnv != 'production';

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (accessToken != null) 'Authorization': 'Bearer $accessToken',
      };

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
  }) async {
    // [人工注释][S1-001] Flutter 正式注册只提交凭证与公开资料，不允许客户端指定 user_id。
    final data = await _jsonRequest(
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
    // [人工注释][S1-015] 注册响应必须同时提供 token + user_id 才建立本机登录作用域，避免半登录状态写入无归属 SQLite 数据。
    _establishAuthenticatedSession(data);
    return data;
  }

  Future<Map<String, dynamic>> login({
    required String email,
    required String password,
  }) async {
    // [人工注释][S1-001] 登录成功后只在当前进程保存正式 Token；持久化会在独立认证持久化任务中处理。
    final data = await _jsonRequest(
      'POST',
      '/auth/login',
      body: {'email': email.trim(), 'password': password},
      authenticated: false,
    );
    // [人工注释][S1-015] 离线 SQLite 必须按认证响应的真实 user_id 分区；token/user_id 原子建立，协议异常时两者都不落入会话。
    _establishAuthenticatedSession(data);
    return data;
  }

  // [人工注释][S1-015] 本机会话身份以服务端认证响应为唯一来源；字段缺失、空值或类型错误都 fail-closed，不创建模糊账号作用域。
  void _establishAuthenticatedSession(Map<String, dynamic> data) {
    final token = data['access_token'];
    final userId = data['user_id'];
    if (token is! String ||
        token.trim().isEmpty ||
        userId is! String ||
        userId.trim().isEmpty) {
      throw ApiException(200, '认证服务返回格式不正确');
    }
    accessToken = token;
    authenticatedUserId = userId;
    _sessionVersion += 1;
  }

  Future<Map<String, dynamic>> getProfile() {
    return _jsonRequest('GET', '/user');
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

  Future<void> deleteMemory(String memoryId) async {
    // [人工注释][S1-019] 删除只调用服务端 soft-delete 入口；客户端删除后不得保留本地“可回答”状态。
    await _jsonRequest('DELETE', '/memories/$memoryId');
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

  Future<Map<String, dynamic>> queryMemory(String question) {
    // [人工注释][S1-013] “问记忆”始终调用服务端 Evidence gate，不在客户端本地拼答案。
    return _jsonRequest(
      'POST',
      '/memory/query',
      body: {'question': question.trim()},
    );
  }

  void logout() {
    accessToken = null;
    // [人工注释][S1-015] 退出登录同时清掉当前本机账号作用域；SQLite 数据保留但下一个账号不能读取它。
    authenticatedUserId = null;
    _sessionVersion += 1;
  }

  // [人工注释][S1-019] 统一传输层显式支持 DELETE；204 空响应也必须沿同一服务端成功链处理，
  // 不能让删除退化成客户端本地隐藏。
  Future<http.Response> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
    bool authenticated = true,
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
    // [人工注释][S1-016] transport 分类只在底层 HTTP 边界捕获 ClientException/TimeoutException；其他异常原样向上，绝不触发离线入队。
    try {
      return switch (method) {
        'GET' => await _http.get(_uri(path), headers: headers),
        'POST' => await _http.post(_uri(path), headers: headers, body: encoded),
        'PATCH' => await _http.patch(_uri(path), headers: headers, body: encoded),
        'DELETE' => await _http.delete(_uri(path), headers: headers, body: encoded),
        _ => throw ArgumentError('Unsupported method: $method'),
      };
    } on http.ClientException catch (exc) {
      throw TransportException('网络连接失败', exc);
    } on TimeoutException catch (exc) {
      throw TransportException('网络请求超时', exc);
    }
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
