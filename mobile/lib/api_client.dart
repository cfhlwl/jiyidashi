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

class JiYiApiClient {
  JiYiApiClient({http.Client? httpClient, String? baseUrl})
      : _http = httpClient ?? http.Client(),
        baseUrl = _resolveApiBaseUrl(baseUrl);

  final http.Client _http;
  final String baseUrl;
  String? accessToken;
  // [人工注释][S1-015] 登录态同时保留服务端签发的 user_id，作为本机 SQLite 数据的账号隔离键；不得用昵称/邮箱猜身份。
  String? authenticatedUserId;

  bool get showDevelopmentEndpoint => _appEnv != 'production';

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (accessToken != null) 'Authorization': 'Bearer $accessToken',
      };

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
    accessToken = data['access_token'] as String;
    // [人工注释][S1-015] 本地账号作用域只接受认证响应里的真实 user_id；缺失/错误格式直接暴露协议错误，不创建无归属离线数据。
    authenticatedUserId = data['user_id'] as String;
    return data;
  }

  Future<Map<String, dynamic>> login({
    required String email,
    required String password,
  }) async {
    // [人工注释][S1-001] 登录成功后只在当前进程保存正式 Token；持久化会在 S1-015 单独实现。
    final data = await _jsonRequest(
      'POST',
      '/auth/login',
      body: {'email': email.trim(), 'password': password},
      authenticated: false,
    );
    accessToken = data['access_token'] as String;
    // [人工注释][S1-015] 离线 SQLite 必须按服务端 user_id 分区，避免同机切换账号后看到或未来发送其他用户的待处理记录。
    authenticatedUserId = data['user_id'] as String;
    return data;
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
  }) {
    // [人工注释][S1-003] 客户端只声明 USER_TEXT capture_source，可信等级继续由服务端决定。
    return _jsonRequest(
      'POST',
      '/memories',
      body: {
        'memory_type': 'NOTE',
        if (title != null && title.trim().isNotEmpty) 'title': title.trim(),
        'content': content.trim(),
        'capture_source': 'USER_TEXT',
      },
    );
  }

  Future<void> deleteMemory(String memoryId) async {
    // [人工注释][S1-019] 删除只调用服务端 soft-delete 入口；客户端删除后不得保留本地“可回答”状态。
    await _jsonRequest('DELETE', '/memories/$memoryId');
  }

  Future<Map<String, dynamic>> rememberObjectLocation({
    required String objectName,
    required String locationText,
  }) async {
    // [人工注释][S1-009] “东西在哪”先建立/复用 Object，再写入有 Evidence 的 ObjectLocation。
    final object = await _jsonRequest(
      'POST',
      '/objects',
      body: {'name': objectName.trim()},
    );
    final objectId = object['id'] as String;
    return _jsonRequest(
      'POST',
      '/objects/$objectId/locations',
      body: {
        'location_text': locationText.trim(),
        'capture_source': 'USER_TEXT',
      },
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
  }

  // [人工注释][S1-019] 统一传输层显式支持 DELETE；204 空响应也必须沿同一服务端成功链处理，
  // 不能让删除退化成客户端本地隐藏。
  Future<http.Response> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
    bool authenticated = true,
  }) async {
    if (authenticated && accessToken == null) {
      throw ApiException(401, '请先登录');
    }
    final headers = authenticated
        ? _headers
        : const {'Content-Type': 'application/json'};
    final encoded = body == null ? null : jsonEncode(body);
    return switch (method) {
      'GET' => await _http.get(_uri(path), headers: headers),
      'POST' => await _http.post(_uri(path), headers: headers, body: encoded),
      'PATCH' => await _http.patch(_uri(path), headers: headers, body: encoded),
      'DELETE' => await _http.delete(_uri(path), headers: headers, body: encoded),
      _ => throw ArgumentError('Unsupported method: $method'),
    };
  }

  // [人工注释][S1-019] DELETE 可能返回 204 无 body；统一解码层把空成功响应视为合法空对象，
  // 同时仍对所有非 2xx 返回真实服务端 detail。
  dynamic _decodeResponse(http.Response response) {
    final dynamic decoded = response.body.isEmpty
        ? <String, dynamic>{}
        : jsonDecode(response.body);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = decoded is Map<String, dynamic> ? decoded['detail'] : null;
      throw ApiException(
        response.statusCode,
        detail?.toString() ?? '请求失败',
      );
    }
    return decoded;
  }

  Future<Map<String, dynamic>> _jsonRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
    bool authenticated = true,
  }) async {
    final decoded = _decodeResponse(
      await _request(method, path, body: body, authenticated: authenticated),
    );
    if (decoded is! Map<String, dynamic>) {
      throw ApiException(200, '服务端返回格式不正确');
    }
    return decoded;
  }

  // [人工注释][S1-011] 物品失效前必须读取用户真实 Object 列表；这个 helper 只解析服务端列表，
  // 不创建、猜测或补造 Object。
  Future<List<Map<String, dynamic>>> _jsonListRequest(String path) async {
    final decoded = _decodeResponse(await _request('GET', path));
    if (decoded is! List<dynamic>) {
      throw ApiException(200, '服务端返回格式不正确');
    }
    return decoded.map((item) {
      if (item is! Map<String, dynamic>) {
        throw ApiException(200, '服务端返回格式不正确');
      }
      return item;
    }).toList();
  }
}
