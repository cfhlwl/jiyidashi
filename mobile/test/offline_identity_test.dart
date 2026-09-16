import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';

const headers = {'content-type': 'application/json; charset=utf-8'};

void main() {
  test('login binds offline ownership to server user id and logout clears it', () async {
    // [人工注释][S1-015] SQLite 账号隔离键必须直接来自成功认证响应，并在退出登录时与 token 一起清除。
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient(
        (_) async => http.Response(
          jsonEncode({
            'access_token': 'token-a',
            'token_type': 'bearer',
            'user_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          }),
          200,
          headers: headers,
        ),
      ),
    );

    await api.login(email: 'a@example.test', password: 'example-password-123');
    expect(api.accessToken, 'token-a');
    expect(api.authenticatedUserId, 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');

    api.logout();
    expect(api.accessToken, isNull);
    expect(api.authenticatedUserId, isNull);
  });

  test('malformed auth response cannot leave a half-authenticated local scope', () async {
    // [人工注释][S1-015] token 或 user_id 任一缺失都必须 fail-closed；否则可能把离线数据写到错误账号作用域。
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient(
        (_) async => http.Response(
          jsonEncode({
            'access_token': 'token-without-user',
            'token_type': 'bearer',
          }),
          200,
          headers: headers,
        ),
      ),
    );

    await expectLater(
      api.login(email: 'a@example.test', password: 'example-password-123'),
      throwsA(
        isA<ApiException>().having(
          (error) => error.message,
          'message',
          '认证服务返回格式不正确',
        ),
      ),
    );
    expect(api.accessToken, isNull);
    expect(api.authenticatedUserId, isNull);
  });
}
