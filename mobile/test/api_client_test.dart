import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';

const jsonHeaders = {'content-type': 'application/json; charset=utf-8'};

http.Response loginResponse() => http.Response(
      jsonEncode({
        'access_token': 'example-token',
        'token_type': 'bearer',
        'user_id': '11111111-1111-1111-1111-111111111111',
      }),
      200,
      headers: jsonHeaders,
    );

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
        if (calls == 1) return loginResponse();

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
        if (calls == 1) return loginResponse();
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

  test('mark stale resolves an existing object without creating a new one', () async {
    var calls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) return loginResponse();
        expect(request.headers['authorization'], 'Bearer example-token');
        if (request.method == 'GET') {
          expect(request.url.path, '/v1/objects');
          return http.Response(
            jsonEncode([
              {
                'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                'name': '护照',
                'category': null,
                'description': null,
                'created_at': '2026-09-16T00:00:00Z',
              }
            ]),
            200,
            headers: jsonHeaders,
          );
        }
        expect(request.method, 'POST');
        expect(
          request.url.path,
          '/v1/objects/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/location/stale',
        );
        return http.Response(
          jsonEncode({
            'id': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
            'object_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            'location_text': '书房',
            'recorded_at': '2026-09-16T00:00:00Z',
            'confidence': 1.0,
            'status': 'STALE',
            'memory_id': 'cccccccc-cccc-cccc-cccc-cccccccccccc',
          }),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'user@example.test', password: 'example-password-123');
    final result = await api.markObjectLocationStale(' 护照 ');
    // [人工注释][S1-011] 客户端失效操作必须命中已有 Object，并以服务端 STALE 状态为准。
    expect(result['status'], 'STALE');
    expect(calls, 3);
  });

  test('memory edit sends only title and content to authenticated PATCH', () async {
    var calls = 0;
    late Map<String, dynamic> requestBody;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) return loginResponse();
        expect(request.method, 'PATCH');
        expect(request.url.path, '/v1/memories/edit-me');
        expect(request.headers['authorization'], 'Bearer example-token');
        requestBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'id': '22222222-2222-2222-2222-222222222222',
            'title': requestBody['title'],
            'content': requestBody['content'],
          }),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'user@example.test', password: 'example-password-123');
    await api.updateMemory(
      'edit-me',
      expectedRevision: 7,
      title: '  新标题  ',
      content: '  修正后的正文  ',
    );

    expect(requestBody, {
      'expected_revision': 7,
      'title': '新标题',
      'content': '修正后的正文',
    });
    expect(requestBody.containsKey('source_type'), isFalse);
    expect(requestBody.containsKey('confidence'), isFalse);
    expect(requestBody.containsKey('is_confirmed'), isFalse);
    expect(requestBody.containsKey('occurred_at'), isFalse);
  });

  test('delete memory uses authenticated DELETE endpoint', () async {
    var calls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) return loginResponse();
        expect(request.method, 'DELETE');
        expect(request.url.path, '/v1/memories/deadbeef');
        expect(request.headers['authorization'], 'Bearer example-token');
        return http.Response('', 204);
      }),
    );

    await api.login(email: 'user@example.test', password: 'example-password-123');
    // [人工注释][S1-019] 删除契约必须走正式 Token，不能只在客户端隐藏记录。
    await api.deleteMemory('deadbeef');
    expect(calls, 2);
  });

  test('privacy controls use server pause and resume endpoints', () async {
    var calls = 0;
    final seen = <String>[];
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) return loginResponse();
        seen.add('${request.method} ${request.url.path}');
        return http.Response(
          jsonEncode({
            'recording_paused': request.url.path != '/v1/privacy/resume',
            'paused_since': '2026-09-16T00:00:00Z',
            'paused_until': '2026-09-16T16:00:00Z',
          }),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'user@example.test', password: 'example-password-123');
    await api.pauseMemory(30);
    await api.pauseMemoryToday();
    await api.resumeMemory();

    // [人工注释][S1-023][S1-024] “今天”交给服务端按用户时区计算，恢复只调用 resume。
    expect(seen, [
      'POST /v1/privacy/pause',
      'POST /v1/privacy/pause/today',
      'POST /v1/privacy/resume',
    ]);
  });

  test('transport and malformed responses keep strict exception classes', () async {
    // [人工注释][S1-016] 真 transport 可离线；2xx 坏 JSON 是 ProtocolException；非 2xx 坏 body 仍是 ApiException。
    final transportApi = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        throw http.ClientException('connection reset', request.url);
      }),
    );
    await expectLater(
      transportApi.login(email: 'u@example.test', password: 'password-123'),
      throwsA(isA<TransportException>()),
    );

    final malformed200 = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((_) async => http.Response('{bad-json', 200)),
    );
    await expectLater(
      malformed200.login(email: 'u@example.test', password: 'password-123'),
      throwsA(isA<ProtocolException>()),
    );

    final malformed502 = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((_) async => http.Response('<html>bad</html>', 502)),
    );
    await expectLater(
      malformed502.login(email: 'u@example.test', password: 'password-123'),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 502)),
    );
  });
  test('media upload keeps auth away from the signed storage PUT', () async {
    var calls = 0;
    final seen = <String>[];
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) return loginResponse();

        seen.add('${request.method} ${request.url}');
        if (request.url.host == 'storage.example.test') {
          expect(request.headers.containsKey('authorization'), isFalse);
          expect(request.headers['content-type'], 'image/jpeg');
          expect(request.bodyBytes, [1, 2, 3]);
          return http.Response('', 200);
        }
        if (request.url.path == '/v1/media/uploads') {
          expect(request.headers['authorization'], 'Bearer example-token');
          return http.Response(
            jsonEncode({
              'id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
              'kind': 'IMAGE',
              'status': 'PENDING',
              'content_type': 'image/jpeg',
              'size_bytes': 3,
              'original_filename': 'photo.jpg',
              'created_at': '2026-09-18T00:00:00Z',
              'completed_at': null,
              'upload': {
                'method': 'PUT',
                'url': 'https://storage.example.test/signed-upload',
                'headers': {'Content-Type': 'image/jpeg'},
                'expires_at': '2026-09-18T00:10:00Z',
              },
            }),
            201,
            headers: jsonHeaders,
          );
        }
        throw StateError('unexpected request: ${request.method} ${request.url}');
      }),
    );

    await api.login(email: 'user@example.test', password: 'example-password-123');
    final session = await api.createMediaUpload(
      clientUploadId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      kind: 'IMAGE',
      contentType: 'image/jpeg',
      sizeBytes: 3,
      originalFilename: 'photo.jpg',
    );
    expect(session.mediaId, 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');
    expect(session.upload, isNotNull);
    await api.uploadSignedMedia(session.upload!, [1, 2, 3]);

    expect(seen, [
      'POST https://example.test/v1/media/uploads',
      'PUT https://storage.example.test/signed-upload',
    ]);
  });


  test('place detail client keeps owner implicit and forwards stable visit cursor', () async {
    var calls = 0;
    final seen = <String>[];
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) return loginResponse();
        seen.add(request.url.toString());
        expect(request.headers['authorization'], 'Bearer example-token');
        if (request.url.path == '/v1/location/places') {
          return http.Response(
            jsonEncode([
              {
                'id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                'name': '家',
                'address': '测试地址',
              }
            ]),
            200,
            headers: jsonHeaders,
          );
        }
        expect(
          request.url.path,
          '/v1/location/places/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        );
        return http.Response(
          jsonEncode({
            'place': {
              'id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
              'name': '家',
            },
            'visits': [],
            'next_cursor': null,
          }),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'user@example.test', password: 'example-password-123');
    final places = await api.listPlaces(limit: 25);
    expect(places.single['name'], '家');
    await api.getPlaceDetail(
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      limit: 20,
      cursor: 'cursor-token',
    );

    expect(seen[0], contains('/v1/location/places?limit=25'));
    expect(seen[1], contains('limit=20'));
    expect(seen[1], contains('cursor=cursor-token'));
    expect(seen[1], isNot(contains('user_id=')));
  });

}
