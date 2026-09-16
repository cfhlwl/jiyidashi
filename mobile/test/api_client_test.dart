import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';

void main() {
  test('register keeps user ownership server-side and stores token in session', () async {
    late Map<String, dynamic> requestBody;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        requestBody = jsonDecode(request.body) as Map<String, dynamic>;
        expect(request.url.path, '/v1/auth/register');
        return http.Response(
          jsonEncode({
            'access_token': 'formal-token',
            'token_type': 'bearer',
            'user_id': '11111111-1111-1111-1111-111111111111',
          }),
          201,
          headers: {'content-type': 'application/json'},
        );
      }),
    );

    // [人工注释][S1-001] 正式注册契约必须证明客户端没有 user_id 所有权。
    await api.register(
      email: 'User@Example.com',
      password: 'correct-horse-battery',
      nickname: '小忆',
    );

    expect(requestBody.containsKey('user_id'), isFalse);
    expect(requestBody['email'], 'User@Example.com');
    expect(api.accessToken, 'formal-token');
  });

  test('text memory uses formal token and USER_TEXT capture source', () async {
    var calls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) {
          return http.Response(
            jsonEncode({
              'access_token': 'formal-token',
              'token_type': 'bearer',
              'user_id': '11111111-1111-1111-1111-111111111111',
            }),
            200,
          );
        }

        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(request.headers['authorization'], 'Bearer formal-token');
        expect(body['capture_source'], 'USER_TEXT');
        expect(body.containsKey('confidence'), isFalse);
        expect(body.containsKey('is_confirmed'), isFalse);
        return http.Response(
          jsonEncode({
            'id': '22222222-2222-2222-2222-222222222222',
            'content': body['content'],
          }),
          201,
        );
      }),
    );

    await api.login(email: 'user@example.com', password: 'secret-password');
    await api.createTextMemory(content: '老张周五下午来公司取合同');
  });

  test('query preserves server evidence for UI rendering', () async {
    var calls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) {
          return http.Response(
            jsonEncode({
              'access_token': 'formal-token',
              'token_type': 'bearer',
              'user_id': '11111111-1111-1111-1111-111111111111',
            }),
            200,
          );
        }
        return http.Response(
          jsonEncode({
            'answer': '护照最后记录在书房左侧柜子第二层。',
            'can_answer': true,
            'certainty': 'confirmed',
            'reason': null,
            'intent': 'FIND_OBJECT',
            'evidence': [
              {
                'kind': 'OBJECT_LOCATION',
                'id': '33333333-3333-3333-3333-333333333333',
                'occurred_at': '2026-09-16T00:00:00Z',
                'excerpt': '护照：书房左侧柜子第二层',
                'confidence': 1.0,
              }
            ],
            'memory_ids': ['44444444-4444-4444-4444-444444444444'],
          }),
          200,
        );
      }),
    );

    await api.login(email: 'user@example.com', password: 'secret-password');
    final result = await api.queryMemory('我的护照在哪里？');

    // [人工注释][S1-014] 客户端契约必须保留服务端 Evidence，不能只剩自由文本答案。
    final evidence = result['evidence'] as List<dynamic>;
    expect(result['certainty'], 'confirmed');
    expect(evidence, hasLength(1));
    expect(
      (evidence.single as Map<String, dynamic>)['excerpt'],
      '护照：书房左侧柜子第二层',
    );
  });
}
