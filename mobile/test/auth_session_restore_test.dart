import 'dart:async';
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

  test('nonterminal refresh HTTP failure preserves durable secure session', () async {
    final store = MemoryAuthSessionStore()
      ..session = const PersistedAuthSession(
        refreshToken: 'retry-refresh-abcdefghijklmnopqrstuvwxyz',
        sessionId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      );
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        return http.Response(
          jsonEncode({'detail': 'TEMPORARY_AUTH_VALIDATION_FAILURE'}),
          400,
          headers: jsonHeaders,
        );
      }),
    );

    final result = await api.restorePersistedSession();

    expect(result, AuthRestoreStatus.serverUnavailable);
    expect(store.session?.refreshToken, 'retry-refresh-abcdefghijklmnopqrstuvwxyz');
    expect(api.authenticatedUserId, isNull);
  });

  test('refresh protocol uncertainty preserves durable secure session', () async {
    final store = MemoryAuthSessionStore()
      ..session = const PersistedAuthSession(
        refreshToken: 'protocol-refresh-abcdefghijklmnopqrstuvwxyz',
        sessionId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      );
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        return http.Response(
          jsonEncode({'access_token': 'partial-only'}),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    final result = await api.restorePersistedSession();

    expect(result, AuthRestoreStatus.serverUnavailable);
    expect(store.session?.refreshToken, 'protocol-refresh-abcdefghijklmnopqrstuvwxyz');
    expect(api.authenticatedUserId, isNull);
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


  test('expired access token refreshes once and retries the authenticated request', () async {
    final store = MemoryAuthSessionStore()..installationId = 'install-retry';
    var call = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        call += 1;
        if (call == 1) {
          expect(request.url.path, '/v1/auth/login');
          return http.Response(
            jsonEncode(sessionPayload(access: 'expired-access')),
            200,
            headers: jsonHeaders,
          );
        }
        if (call == 2) {
          expect(request.url.path, '/v1/user');
          expect(request.headers['authorization'], 'Bearer expired-access');
          return http.Response(
            jsonEncode({'detail': 'INVALID_ACCESS_TOKEN'}),
            401,
            headers: jsonHeaders,
          );
        }
        if (call == 3) {
          expect(request.url.path, '/v1/auth/refresh');
          return http.Response(
            jsonEncode(
              sessionPayload(
                access: 'fresh-access',
                refresh: 'fresh-refresh-abcdefghijklmnopqrstuvwxyz',
              ),
            ),
            200,
            headers: jsonHeaders,
          );
        }
        expect(call, 4);
        expect(request.url.path, '/v1/user');
        expect(request.headers['authorization'], 'Bearer fresh-access');
        return http.Response(
          jsonEncode({
            'id': '11111111-1111-4111-8111-111111111111',
            'nickname': 'Owner',
            'timezone': 'Asia/Shanghai',
            'locale': 'zh-CN',
            'elder_mode_enabled': false,
            'created_at': '2026-09-30T00:00:00Z',
          }),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'owner@example.test', password: 'password-123456');
    final profile = await api.getProfile();

    expect(profile['nickname'], 'Owner');
    expect(api.accessToken, 'fresh-access');
    expect(store.session?.refreshToken, 'fresh-refresh-abcdefghijklmnopqrstuvwxyz');
    expect(call, 4);
  });


  test('access rotation preserves durable session authority version', () async {
    final store = MemoryAuthSessionStore()..installationId = 'install-version';
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

    await api.login(email: 'owner@example.test', password: 'password-123456');
    final version = api.sessionVersion;
    final sessionId = api.authenticatedSessionId;

    await api.revalidateAuthenticatedOwnerAuthority();

    expect(api.sessionVersion, version);
    expect(api.authenticatedSessionId, sessionId);
    expect(api.accessToken, 'access-v2');
  });

  test('logout invalidates local authority synchronously before network completes', () async {
    final store = MemoryAuthSessionStore()..installationId = 'install-sync-logout';
    final release = Completer<void>();
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
        await release.future;
        return http.Response(
          jsonEncode({'accepted': true}),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'owner@example.test', password: 'password-123456');
    final before = api.sessionVersion;
    final pending = api.logout();

    expect(api.authenticatedUserId, isNull);
    expect(api.accessToken, isNull);
    expect(api.sessionVersion, greaterThan(before));

    release.complete();
    await pending;
    expect(store.session, isNull);
  });


  test('expired access logout refreshes only to revoke the server session', () async {
    final store = MemoryAuthSessionStore()..installationId = 'install-expired-logout';
    var call = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        call += 1;
        if (call == 1) {
          return http.Response(
            jsonEncode(sessionPayload(access: 'expired-access')),
            200,
            headers: jsonHeaders,
          );
        }
        if (call == 2) {
          expect(request.url.path, '/v1/auth/logout');
          expect(request.headers['authorization'], 'Bearer expired-access');
          return http.Response(
            jsonEncode({'detail': 'INVALID_ACCESS_TOKEN'}),
            401,
            headers: jsonHeaders,
          );
        }
        if (call == 3) {
          expect(request.url.path, '/v1/auth/refresh');
          expect(request.headers.containsKey('authorization'), isFalse);
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['refresh_token'], 'refresh-v1-abcdefghijklmnopqrstuvwxyz');
          return http.Response(
            jsonEncode(
              sessionPayload(
                access: 'revoke-only-access',
                refresh: 'revoke-only-refresh-abcdefghijklmnopqrstuvwxyz',
              ),
            ),
            200,
            headers: jsonHeaders,
          );
        }
        expect(call, 4);
        expect(request.url.path, '/v1/auth/logout');
        expect(request.headers['authorization'], 'Bearer revoke-only-access');
        return http.Response(
          jsonEncode({'accepted': true}),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'owner@example.test', password: 'password-123456');
    await api.logout();

    expect(call, 4);
    expect(api.authenticatedUserId, isNull);
    expect(api.accessToken, isNull);
    expect(store.session, isNull);
  });

  test('expired access logout-all refreshes and revokes with fresh authority', () async {
    final store = MemoryAuthSessionStore()..installationId = 'install-expired-logout-all';
    var call = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        call += 1;
        if (call == 1) {
          return http.Response(
            jsonEncode(sessionPayload(access: 'expired-access')),
            200,
            headers: jsonHeaders,
          );
        }
        if (call == 2) {
          expect(request.url.path, '/v1/auth/logout-all');
          expect(request.headers['authorization'], 'Bearer expired-access');
          return http.Response(
            jsonEncode({'detail': 'INVALID_ACCESS_TOKEN'}),
            401,
            headers: jsonHeaders,
          );
        }
        if (call == 3) {
          expect(request.url.path, '/v1/auth/refresh');
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['refresh_token'], 'refresh-v1-abcdefghijklmnopqrstuvwxyz');
          return http.Response(
            jsonEncode(
              sessionPayload(
                access: 'logout-all-access',
                refresh: 'logout-all-refresh-abcdefghijklmnopqrstuvwxyz',
              ),
            ),
            200,
            headers: jsonHeaders,
          );
        }
        expect(call, 4);
        expect(request.url.path, '/v1/auth/logout-all');
        expect(request.headers['authorization'], 'Bearer logout-all-access');
        return http.Response(
          jsonEncode({'accepted': true}),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'owner@example.test', password: 'password-123456');
    await api.logoutAll();

    expect(call, 4);
    expect(api.authenticatedUserId, isNull);
    expect(api.accessToken, isNull);
    expect(store.session, isNull);
  });

  test('late refresh response cannot restore a session after logout', () async {
    final store = MemoryAuthSessionStore()..installationId = 'install-late-logout';
    final lateRefresh = Completer<http.Response>();
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
        if (call == 2) {
          expect(request.url.path, '/v1/auth/refresh');
          return lateRefresh.future;
        }
        expect(call, 3);
        expect(request.url.path, '/v1/auth/logout');
        return http.Response(
          jsonEncode({'accepted': true}),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'owner@example.test', password: 'password-123456');
    final staleRefresh = api.revalidateAuthenticatedOwnerAuthority();
    final staleExpectation = expectLater(
      staleRefresh,
      throwsA(isA<ProtocolException>()),
    );
    await Future<void>.delayed(Duration.zero);

    await api.logout();
    expect(store.session, isNull);
    expect(api.authenticatedUserId, isNull);

    lateRefresh.complete(
      http.Response(
        jsonEncode(
          sessionPayload(
            access: 'late-access',
            refresh: 'late-refresh-abcdefghijklmnopqrstuvwxyz',
          ),
        ),
        200,
        headers: jsonHeaders,
      ),
    );
    await staleExpectation;

    expect(store.session, isNull);
    expect(api.authenticatedUserId, isNull);
    expect(api.accessToken, isNull);
  });

  test('late account A refresh cannot overwrite account B after switch', () async {
    const userA = '11111111-1111-4111-8111-111111111111';
    const userB = '22222222-2222-4222-8222-222222222222';
    const sessionA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
    const sessionB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
    final store = MemoryAuthSessionStore()..installationId = 'install-switch';
    final lateRefresh = Completer<http.Response>();
    var call = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        call += 1;
        if (call == 1) {
          return http.Response(
            jsonEncode(
              sessionPayload(
                access: 'access-a',
                refresh: 'refresh-a-abcdefghijklmnopqrstuvwxyz',
                session: sessionA,
                user: userA,
              ),
            ),
            200,
            headers: jsonHeaders,
          );
        }
        if (call == 2) {
          expect(request.url.path, '/v1/auth/refresh');
          return lateRefresh.future;
        }
        if (call == 3) {
          expect(request.url.path, '/v1/auth/logout');
          return http.Response(
            jsonEncode({'accepted': true}),
            200,
            headers: jsonHeaders,
          );
        }
        expect(call, 4);
        expect(request.url.path, '/v1/auth/login');
        return http.Response(
          jsonEncode(
            sessionPayload(
              access: 'access-b',
              refresh: 'refresh-b-abcdefghijklmnopqrstuvwxyz',
              session: sessionB,
              user: userB,
            ),
          ),
          200,
          headers: jsonHeaders,
        );
      }),
    );

    await api.login(email: 'a@example.test', password: 'password-123456');
    final staleRefresh = api.revalidateAuthenticatedOwnerAuthority();
    final staleExpectation = expectLater(
      staleRefresh,
      throwsA(isA<ProtocolException>()),
    );
    await Future<void>.delayed(Duration.zero);

    await api.logout();
    await api.login(email: 'b@example.test', password: 'password-123456');
    expect(api.authenticatedUserId, userB);
    expect(store.session?.sessionId, sessionB);
    expect(store.session?.refreshToken, 'refresh-b-abcdefghijklmnopqrstuvwxyz');

    lateRefresh.complete(
      http.Response(
        jsonEncode(
          sessionPayload(
            access: 'late-access-a',
            refresh: 'late-refresh-a-abcdefghijklmnopqrstuvwxyz',
            session: sessionA,
            user: userA,
          ),
        ),
        200,
        headers: jsonHeaders,
      ),
    );
    await staleExpectation;

    expect(api.authenticatedUserId, userB);
    expect(api.authenticatedSessionId, sessionB);
    expect(api.accessToken, 'access-b');
    expect(store.session?.sessionId, sessionB);
    expect(store.session?.refreshToken, 'refresh-b-abcdefghijklmnopqrstuvwxyz');
  });

}
