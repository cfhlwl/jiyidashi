import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';

const jsonHeaders = {'content-type': 'application/json; charset=utf-8'};

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
            'access_token': 'example-token',
            'token_type': 'bearer',
            'user_id': '11111111-1111-1111-1111-111111111111',
          }),
          201,
          headers: jsonHeaders,
        );
      }),
    );

    // [人工注释][S1-001] 正式注册契约必须证明客户端没有 user_id 所有权。
    await api.register(
      email: 'user@example.test',
      password: 'example-password-123',
      nickname: '测试用户',
    );

    expect(requestBody.containsKey('user_id'), isFalse);
    expect(requestBody['email'], 'user@example.test');
    expect(api.accessToken, 'example-token');
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
              'access_token': 'example-token',
              'token_type': 'bearer',
              'user_id': '11111111-1111-1111-1111-111111111111',
            }),
            200,
            headers: jsonHeaders,
          );
        }

        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(request.headers['authorization'], 'Bearer example-token');
        expect(body['capture_source'], 'USER_TEXT');
        expect(body.containsKey('confidence'), isFalse);
        expect(body.containsKey('is_confirmed'), isFalse);
        return http.Response(
          jsonEncode({
            'id': '22222222-2222-2222-2222-222222222222',
            'content': body['content'],
          }),
          201,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'user@example.test', password: 'example-password-123');
    await api.createTextMemory(content: '测试中文记忆内容');
  });

  test('query preserves real memory source evidence for UI rendering', () async {
    var calls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) {
          return http.Response(
            jsonEncode({
              'access_token': 'example-token',
              'token_type': 'bearer',
              'user_id': '11111111-1111-1111-1111-111111111111',
            }),
            200,
            headers: jsonHeaders,
          );
        }
        return http.Response(
          jsonEncode({
            'answer': '物品最后记录在书房。',
            'can_answer': true,
            'certainty': 'confirmed',
            'reason': null,
            'intent': 'FIND_OBJECT',
            'evidence': [
              {
                'kind': 'OBJECT_LOCATION',
                'id': '33333333-3333-3333-3333-333333333333',
                'source_type': 'USER_TEXT',
                'memory_source_id': '55555555-5555-5555-5555-555555555555',
                'occurred_at': '2026-09-16T00:00:00Z',
                'excerpt': '物品：书房',
                'confidence': 1.0,
              }
            ],
            'memory_ids': ['44444444-4444-4444-4444-444444444444'],
          }),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'user@example.test', password: 'example-password-123');
    final result = await api.queryMemory('物品在哪里？');

    // [人工注释][S1-FIX-002] 客户端必须保留真实 source_type 和 MemorySource ID，不能把 kind 当来源。
    final evidence = result['evidence'] as List<dynamic>;
    final firstEvidence = evidence.single as Map<String, dynamic>;
    expect(result['can_answer'], isTrue);
    expect(result['certainty'], 'confirmed');
    expect(evidence, hasLength(1));
    expect(firstEvidence['excerpt'], '物品：书房');
    expect(firstEvidence['kind'], 'OBJECT_LOCATION');
    expect(firstEvidence['source_type'], 'USER_TEXT');
    expect(
      firstEvidence['memory_source_id'],
      '55555555-5555-5555-5555-555555555555',
    );
  });
}
