import 'dart:async';
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
const _userBId = '66666666-6666-4666-8666-666666666666';
const _sessionBId = '77777777-7777-4777-8777-777777777777';
const _unlinkRequestId = '88888888-8888-4888-8888-888888888888';

Map<String, dynamic> _token({String userId = _userId, String sessionId = _sessionId}) => {
      'access_token': 'access-token',
      'refresh_token': 'refresh-token-long-enough-1234567890',
      'session_id': sessionId,
      'token_type': 'bearer',
      'user_id': userId,
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
    expect(
      () => AuthIdentityRead.fromJson({
        'identity_id': '33333333-3333-4333-8333-333333333333',
        'provider': 'PHONE',
        'subject_hint': '+86138****5678',
        'linked_at': '2026-10-01T00:00:00Z',
      }),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      () => AuthIdentityRead.fromJson({
        'identity_id': '------------------------------------',
        'provider': 'PHONE',
        'subject_hint': '+86138****5678',
        'verified_at': null,
        'linked_at': '2026-10-01T00:00:00Z',
      }),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      () => AuthIdentityRead.fromJson({
        'identity_id': '33333333-3333-4333-8333-333333333333',
        'provider': 'PHONE',
        'subject_hint': '+86138****5678',
        'verified_at': null,
        'linked_at': '2026-10-01 00:00:00',
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
            'request_id': calls == 2
                ? '55555555-5555-4555-8555-555555555555'
                : _unlinkRequestId,
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
      requestId: _unlinkRequestId,
      reauthCredential: 'opaque-reauth',
    );
    expect(linked.operation, 'LINK');
    expect(unlinked.operation, 'UNLINK');
    expect(calls, 3);
  });

  test('typed mutation adapters reject UUIDs with invalid version or variant bits', () async {
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        if (request.url.path == '/v1/auth/login') {
          return http.Response(jsonEncode(_token()), 200, headers: _headers);
        }
        fail('malformed mutation input must not reach the server');
      }),
    );
    await api.login(email: 'a@example.test', password: 'password-123456');

    await expectLater(
      api.linkAuthIdentity(
        requestId: '55555555-5555-0555-8555-555555555555',
        credential: 'opaque-provider-proof',
        reauthCredential: 'opaque-reauth',
      ),
      throwsA(isA<ProtocolException>()),
    );
    await expectLater(
      api.unlinkAuthIdentity(
        identityId: '33333333-3333-4333-7333-333333333333',
        requestId: _unlinkRequestId,
        reauthCredential: 'opaque-reauth',
      ),
      throwsA(isA<ProtocolException>()),
    );
    await expectLater(
      api.unlinkAuthIdentity(
        identityId: '33333333-3333-4333-8333-333333333333',
        requestId: '88888888-8888-4888-0888-888888888888',
        reauthCredential: 'opaque-reauth',
      ),
      throwsA(isA<ProtocolException>()),
    );
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
    expect(find.textContaining('a***@example.test'), findsOneWidget);
    expect(find.text('当前未配置可用的身份绑定服务，绑定和解绑已安全禁用。'), findsOneWidget);
    final bind = find.text('绑定新的登录方式');
    expect(tester.widget<FilledButton>(find.ancestor(of: bind, matching: find.byType(FilledButton))).onPressed, isNull);
    expect(mutationCalls, 0);
  });

  testWidgets('clears A identities before B and rejects late A response', (tester) async {
    final pendingA = Completer<http.Response>();
    var identityCalls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        if (request.url.path == '/v1/auth/login') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(
            jsonEncode(body['email'] == 'b@example.test'
                ? _token(userId: _userBId, sessionId: _sessionBId)
                : _token()),
            200,
            headers: _headers,
          );
        }
        if (request.url.path == '/v1/auth/logout') {
          return http.Response('{}', 200, headers: _headers);
        }
        expect(request.url.path, '/v1/auth/identities');
        identityCalls += 1;
        if (identityCalls == 1) return pendingA.future;
        return http.Response(
          jsonEncode({'identities': [
            {
              ..._identities().first,
              'subject_hint': 'b***@example.test',
            },
          ]}),
          200,
          headers: _headers,
        );
      }),
    );
    await api.login(email: 'a@example.test', password: 'password-123456');
    await tester.pumpWidget(MaterialApp(home: AccountSecurityPage(api: api)));
    await tester.pump();

    await api.logout();
    await api.login(email: 'b@example.test', password: 'password-123456');
    await tester.pumpAndSettle();
    expect(find.textContaining('b***@example.test'), findsOneWidget);
    expect(find.textContaining('a***@example.test'), findsNothing);

    pendingA.complete(http.Response(
      jsonEncode({'identities': _identities()}),
      200,
      headers: _headers,
    ));
    await tester.pumpAndSettle();
    expect(find.textContaining('b***@example.test'), findsOneWidget);
    expect(find.textContaining('a***@example.test'), findsNothing);
  });

  testWidgets('rebinds an existing page when the API object changes', (tester) async {
    JiYiApiClient makeApi(String subjectHint, String userId, String sessionId) {
      return JiYiApiClient(
        baseUrl: 'https://example.test/v1',
        httpClient: MockClient((request) async {
          if (request.url.path == '/v1/auth/login') {
            return http.Response(
              jsonEncode(_token(userId: userId, sessionId: sessionId)),
              200,
              headers: _headers,
            );
          }
          return http.Response(jsonEncode({'identities': [
            {..._identities().first, 'subject_hint': subjectHint},
          ]}), 200, headers: _headers);
        }),
      );
    }

    final apiA = makeApi('a***@example.test', _userId, _sessionId);
    final apiB = makeApi('b***@example.test', _userBId, _sessionBId);
    await apiA.login(email: 'a@example.test', password: 'password-123456');
    await apiB.login(email: 'b@example.test', password: 'password-123456');
    await tester.pumpWidget(MaterialApp(home: AccountSecurityPage(api: apiA)));
    await tester.pumpAndSettle();
    expect(find.textContaining('a***@example.test'), findsOneWidget);

    await tester.pumpWidget(MaterialApp(home: AccountSecurityPage(api: apiB)));
    await tester.pumpAndSettle();
    expect(find.textContaining('a***@example.test'), findsNothing);
    expect(find.textContaining('b***@example.test'), findsOneWidget);
  });

  testWidgets('ignores a late A error after B becomes the current account', (tester) async {
    final pendingA = Completer<http.Response>();
    var identityCalls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        if (request.url.path == '/v1/auth/login') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(
            jsonEncode(body['email'] == 'b@example.test'
                ? _token(userId: _userBId, sessionId: _sessionBId)
                : _token()),
            200,
            headers: _headers,
          );
        }
        if (request.url.path == '/v1/auth/logout') {
          return http.Response('{}', 200, headers: _headers);
        }
        expect(request.url.path, '/v1/auth/identities');
        identityCalls += 1;
        if (identityCalls == 1) return pendingA.future;
        return http.Response(
          jsonEncode({'identities': [
            {..._identities().first, 'subject_hint': 'b***@example.test'},
          ]}),
          200,
          headers: _headers,
        );
      }),
    );
    await api.login(email: 'a@example.test', password: 'password-123456');
    await tester.pumpWidget(MaterialApp(home: AccountSecurityPage(api: api)));
    await tester.pump();

    await api.logout();
    await api.login(email: 'b@example.test', password: 'password-123456');
    await tester.pumpAndSettle();
    expect(find.textContaining('b***@example.test'), findsOneWidget);

    pendingA.completeError(StateError('late network failure'));
    await tester.pumpAndSettle();
    expect(find.textContaining('b***@example.test'), findsOneWidget);
    expect(find.text('暂时无法读取登录身份，请稍后重试'), findsNothing);
  });
}
