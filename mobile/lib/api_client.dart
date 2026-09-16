import 'dart:convert';

import 'package:http/http.dart' as http;

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
        baseUrl = baseUrl ??
            const String.fromEnvironment(
              'API_BASE_URL',
              defaultValue: 'http://127.0.0.1:8000/v1',
            );

  final http.Client _http;
  final String baseUrl;
  String? accessToken;

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
  }

  Future<Map<String, dynamic>> _jsonRequest(
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
    final response = switch (method) {
      'GET' => await _http.get(_uri(path), headers: headers),
      'POST' => await _http.post(_uri(path), headers: headers, body: encoded),
      'PATCH' => await _http.patch(_uri(path), headers: headers, body: encoded),
      _ => throw ArgumentError('Unsupported method: $method'),
    };

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
    if (decoded is! Map<String, dynamic>) {
      throw ApiException(response.statusCode, '服务端返回格式不正确');
    }
    return decoded;
  }
}
