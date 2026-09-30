import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';

const jsonHeaders = {'content-type': 'application/json; charset=utf-8'};

Map<String, dynamic> sessionPayload({
  String access = 'access-v1',
  String refresh = 'refresh-v1-abcdefghijklmnopqrstuvwxyz',
  String session = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  String user = '11111111-1111-4111-8111-111111111111',
}) =>
    {
      'access_token': access,
      'refresh_token': refresh,
      'session_id': session,
      'token_type': 'bearer',
      'user_id': user,
      'access_expires_at': '2030-09-30T00:15:00Z',
      'refresh_expires_at': '2030-10-30T00:00:00Z',
      'account_deletion_in_progress': false,
    };

void main() {
  test('login persists refresh/session only and user identity remains server-owned', () async {
    final store = MemoryAuthSessionStore()..installationId = 'install-a';
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        expect(request.url.path, '/v1/auth/login');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['device_id'], 'install-a');
        return http.Response(
          jsonEncode(sessionPayload()),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'owner@example.test', password: 'password-123456');

    expect(api.authenticatedUserId, '11111111-1111-4111-8111-111111111111');
    expect(store.session?.refreshToken, 'refresh-v1-abcdefghijklmnopqrstuvwxyz');
    expect(store.session?.sessionId, 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');
    // PersistedAuthSession intentionally has no user/access/password fields.
    expect(store.session!.toJson().keys, {'refresh_token', 'session_id'});
  });

  test('cold start restores owner only after server refresh succeeds', () async {
    final store = MemoryAuthSessionStore()
      ..installationId = 'install-b'
      ..session = const PersistedAuthSession(
        refreshToken: 'persisted-refresh-abcdefghijklmnopqrstuvwxyz',
        sessionId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      );
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        expect(request.url.path, '/v1/auth/refresh');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['refresh_token'], 'persisted-refresh-abcdefghijklmnopqrstuvwxyz');
        return http.Response(
          jsonEncode(
            sessionPayload(
              access: 'access-restored',
              refresh: 'rotated-refresh-abcdefghijklmnopqrstuvwxyz',
            ),
          ),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    expect(api.authenticatedUserId, isNull);
    final result = await api.restorePersistedSession();

    expect(result, AuthRestoreStatus.restored);
    expect(api.authenticatedUserId, '11111111-1111-4111-8111-111111111111');
    expect(api.accessToken, 'access-restored');
    expect(store.session?.refreshToken, 'rotated-refresh-abcdefghijklmnopqrstuvwxyz');
  });

  test('invalid cold-start refresh clears secure session and publishes no owner', () async {
    final store = MemoryAuthSessionStore()
      ..session = const PersistedAuthSession(
        refreshToken: 'invalid-refresh-abcdefghijklmnopqrstuvwxyz',
        sessionId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      );
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        return http.Response(
          jsonEncode({'detail': 'INVALID_REFRESH_TOKEN'}),
          401,
          headers: jsonHeaders,
        );
      }),
    );

    final result = await api.restorePersistedSession();

    expect(result, AuthRestoreStatus.invalidSession);
    expect(store.session, isNull);
    expect(api.authenticatedUserId, isNull);
    expect(api.accessToken, isNull);
  });

  test('network-unavailable restore keeps refresh material but no local authority', () async {
    final store = MemoryAuthSessionStore()
      ..session = const PersistedAuthSession(
        refreshToken: 'offline-refresh-abcdefghijklmnopqrstuvwxyz',
        sessionId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      );
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        throw http.ClientException('offline', request.url);
      }),
    );

    final result = await api.restorePersistedSession();

    expect(result, AuthRestoreStatus.serverUnavailable);
    expect(store.session, isNotNull);
    expect(api.authenticatedUserId, isNull);
    expect(api.accessToken, isNull);
  });

  test('logout revokes server session before removing secure refresh material', () async {
    final store = MemoryAuthSessionStore()..installationId = 'install-logout';
    var call = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        call += 1;
        if (call == 1) {
          return http.Response(
            jsonEncode(sessionPayload()),
            200,
            headers: jsonHeaders,
          );
        }
        expect(request.url.path, '/v1/auth/logout');
        expect(request.headers['authorization'], 'Bearer access-v1');
        return http.Response(
          jsonEncode({'accepted': true}),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'owner@example.test', password: 'password-123456');
    expect(store.session, isNotNull);
    await api.logout();

    expect(store.session, isNull);
    expect(api.authenticatedUserId, isNull);
    expect(api.accessToken, isNull);
  });

  test('background authority seam stays false until server session exists', () async {
    final store = MemoryAuthSessionStore()..installationId = 'install-authority';
    var calls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) {
          return http.Response(
            jsonEncode(sessionPayload()),
            200,
            headers: jsonHeaders,
          );
        }
        expect(request.url.path, '/v1/auth/refresh');
        return http.Response(
          jsonEncode(
            sessionPayload(
              access: 'access-v2',
              refresh: 'refresh-v2-abcdefghijklmnopqrstuvwxyz',
            ),
          ),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    expect(api.hasFreshAuthenticatedOwnerAuthority, isFalse);
    expect(api.authenticatedSessionId, isNull);

    await api.login(email: 'owner@example.test', password: 'password-123456');
    expect(api.hasFreshAuthenticatedOwnerAuthority, isTrue);
    expect(
      api.authenticatedSessionId,
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    );

    await api.revalidateAuthenticatedOwnerAuthority();
    expect(calls, 2);
    expect(api.accessToken, 'access-v2');
    expect(api.hasFreshAuthenticatedOwnerAuthority, isTrue);
  });

}
