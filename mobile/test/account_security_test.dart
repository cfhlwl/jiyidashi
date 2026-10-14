import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/account_security_page.dart';
import 'package:jiyidashi/api_client.dart';

const _headers = {'content-type': 'application/json'};
const _userId = '11111111-1111-4111-8111-111111111111';
const _sessionId = '22222222-2222-4222-8222-222222222222';

Map<String, dynamic> _token() => {
      'access_token': 'access-token',
      'refresh_token': 'refresh-token-long-enough-1234567890',
      'session_id': _sessionId,
      'token_type': 'bearer',
      'user_id': _userId,
      'access_expires_at': '2099-01-01T00:00:00Z',
      'refresh_expires_at': '2099-02-01T00:00:00Z',
      'account_deletion_in_progress': false,
    };

List<Map<String, dynamic>> _identities() => [
      {
        'identity_id': '33333333-3333-4333-8333-333333333333',
        'provider': 'EMAIL_PASSWORD',
        'subject_hint': 'a***@example.test',
        'verified_at': '2026-10-01T00:00:00Z',
        'linked_at': '2026-10-01T00:00:00Z',
      },
      {
        'identity_id': '44444444-4444-4444-8444-444444444444',
        'provider': 'PHONE',
        'subject_hint': '+86138****5678',
        'verified_at': null,
        'linked_at': '2026-10-02T00:00:00Z',
      },
    ];

void main() {
  test('typed identity list rejects missing authority fields', () {
    expect(
      () => AuthIdentityRead.fromJson({
        'identity_id': '33333333-3333-4333-8333-333333333333',
        'provider': 'PHONE',
        'subject_hint': '+86138****5678',
        'verified_at': null,
      }),
      throwsA(isA<ProtocolException>()),
    );
  });

  test('identity client reads only server list and keeps provider credentials out', () async {
    var calls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (request.url.path == '/v1/auth/login') {
          return http.Response(jsonEncode(_token()), 200, headers: _headers);
        }
        expect(request.url.path, '/v1/auth/identities');
        expect(request.method, 'GET');
        expect(request.body, isEmpty);
        expect(request.headers['authorization'], 'Bearer access-token');
        return http.Response(jsonEncode({'identities': _identities()}), 200, headers: _headers);
      }),
    );

    await api.login(email: 'a@example.test', password: 'password-123456');
    final identities = await api.fetchAuthIdentities();
    expect(calls, 2);
    expect(identities.map((identity) => identity.provider), ['EMAIL_PASSWORD', 'PHONE']);
    expect(identities.last.verifiedAt, isNull);
  });

  test('typed mutation adapters use opaque proof and stable request ids', () async {
    var calls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) return http.Response(jsonEncode(_token()), 200, headers: _headers);
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['credential'], isNot('a@example.test'));
        expect(body['reauth_credential'], 'opaque-reauth');
        expect(request.url.path, calls == 2 ? '/v1/auth/identities/link' : '/v1/auth/identities/33333333-3333-4333-8333-333333333333');
        return http.Response(
          jsonEncode({
            'request_id': '55555555-5555-4555-8555-555555555555',
            'operation': calls == 2 ? 'LINK' : 'UNLINK',
            'identity': calls == 2 ? _identities().first : null,
          }),
          200,
          headers: _headers,
        );
      }),
    );
    await api.login(email: 'a@example.test', password: 'password-123456');
    final linked = await api.linkAuthIdentity(
      requestId: '55555555-5555-4555-8555-555555555555',
      credential: 'opaque-provider-proof',
      reauthCredential: 'opaque-reauth',
    );
    final unlinked = await api.unlinkAuthIdentity(
      identityId: '33333333-3333-4333-8333-333333333333',
      requestId: linked.requestId,
      reauthCredential: 'opaque-reauth',
    );
    expect(linked.operation, 'LINK');
    expect(unlinked.operation, 'UNLINK');
    expect(calls, 3);
  });

  testWidgets('provider OFF renders identities but does not expose mutation action', (tester) async {
    var mutationCalls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        if (request.url.path == '/v1/auth/login') {
          return http.Response(jsonEncode(_token()), 200, headers: _headers);
        }
        if (request.url.path == '/v1/auth/identities') {
          return http.Response(jsonEncode({'identities': _identities()}), 200, headers: _headers);
        }
        mutationCalls += 1;
        return http.Response('{}', 500, headers: _headers);
      }),
    );
    await api.login(email: 'a@example.test', password: 'password-123456');

    await tester.pumpWidget(MaterialApp(home: AccountSecurityPage(api: api)));
    await tester.pumpAndSettle();

    expect(find.text('账号与安全'), findsOneWidget);
    expect(find.text('a***@example.test'), findsOneWidget);
    expect(find.text('当前未配置可用的身份绑定服务，绑定和解绑已安全禁用。'), findsOneWidget);
    final bind = find.text('绑定新的登录方式');
    expect(tester.widget<FilledButton>(find.ancestor(of: bind, matching: find.byType(FilledButton))).onPressed, isNull);
    expect(mutationCalls, 0);
  });
}
