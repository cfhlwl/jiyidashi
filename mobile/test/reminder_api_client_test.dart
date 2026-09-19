import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';

const jsonHeaders = {'content-type': 'application/json; charset=utf-8'};

http.Response _loginResponse() => http.Response(
      jsonEncode({
        'access_token': 'example-token',
        'token_type': 'bearer',
        'user_id': '11111111-1111-1111-1111-111111111111',
      }),
      200,
      headers: jsonHeaders,
    );

void main() {
  test('reminder client sends UTC timestamp and uses transition endpoints', () async {
    var calls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) return _loginResponse();

        expect(request.headers['authorization'], 'Bearer example-token');
        if (calls == 2) {
          expect(request.method, 'POST');
          expect(request.url.path, '/v1/reminders');
          expect(
            request.headers['idempotency-key'],
            'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          );
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(
            body['memory_id'],
            '22222222-2222-2222-2222-222222222222',
          );
          expect(body['title'], '提交材料');
          expect(body['content'], '带上盖章件');
          expect(body['remind_at'], '2026-09-20T01:30:00.000Z');
          return http.Response(
            jsonEncode({
              'id': '33333333-3333-3333-3333-333333333333',
              'user_id': '11111111-1111-1111-1111-111111111111',
              'memory_id': body['memory_id'],
              'title': body['title'],
              'content': body['content'],
              'remind_at': body['remind_at'],
              'status': 'PENDING',
              'created_at': '2026-09-19T00:00:00Z',
            }),
            201,
            headers: jsonHeaders,
          );
        }
        if (calls == 3) {
          expect(request.method, 'GET');
          expect(request.url.path, '/v1/reminders');
          expect(request.url.queryParameters['status'], 'PENDING');
          return http.Response('[]', 200, headers: jsonHeaders);
        }
        if (calls == 4) {
          expect(request.method, 'POST');
          expect(
            request.url.path,
            '/v1/reminders/33333333-3333-3333-3333-333333333333/done',
          );
        } else {
          expect(request.method, 'POST');
          expect(
            request.url.path,
            '/v1/reminders/33333333-3333-3333-3333-333333333333/cancel',
          );
        }
        return http.Response(
          jsonEncode({
            'id': '33333333-3333-3333-3333-333333333333',
            'user_id': '11111111-1111-1111-1111-111111111111',
            'memory_id': '22222222-2222-2222-2222-222222222222',
            'title': '提交材料',
            'content': null,
            'remind_at': '2026-09-20T01:30:00Z',
            'status': calls == 4 ? 'DONE' : 'CANCELLED',
            'created_at': '2026-09-19T00:00:00Z',
          }),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(
      email: 'user@example.test',
      password: 'example-password-123',
    );
    await api.createReminder(
      memoryId: '22222222-2222-2222-2222-222222222222',
      title: ' 提交材料 ',
      content: ' 带上盖章件 ',
      remindAt: DateTime.parse('2026-09-20T09:30:00+08:00'),
      clientUuid: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    );
    await api.listReminders(status: 'PENDING');
    await api.completeReminder('33333333-3333-3333-3333-333333333333');
    await api.cancelReminder('33333333-3333-3333-3333-333333333333');

    expect(calls, 5);
  });
}
