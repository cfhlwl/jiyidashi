import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';
import 'package:jiyidashi/notification_client.dart';

const _jsonHeaders = {'content-type': 'application/json; charset=utf-8'};

http.Response _loginResponse({
  String userId = '11111111-1111-4111-8111-111111111111',
  String sessionId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
}) {
  return http.Response(
    jsonEncode({
      'access_token': 'access-token',
      'refresh_token': 'refresh-token-value-1234567890',
      'session_id': sessionId,
      'token_type': 'bearer',
      'user_id': userId,
      'access_expires_at': '2030-10-07T12:00:00Z',
      'refresh_expires_at': '2030-11-07T12:00:00Z',
    }),
    200,
    headers: _jsonHeaders,
  );
}

class FakeNativeNotificationBridge implements NativeNotificationBridge {
  FakeNativeNotificationBridge(this.current);

  NativePushStatus current;
  NativePushEventHandler? handler;
  int permissionRequests = 0;
  int registrationRequests = 0;
  int unregisterRequests = 0;

  @override
  Future<void> attach(NativePushEventHandler value) async {
    handler = value;
  }

  @override
  Future<NativePushStatus> status() async => current;

  @override
  Future<NativePushStatus> requestPermission() async {
    permissionRequests += 1;
    return current;
  }

  @override
  Future<NativePushStatus> registerForPush() async {
    registrationRequests += 1;
    return current;
  }

  @override
  Future<void> unregisterFromPush() async {
    unregisterRequests += 1;
  }

  Future<void> emit(NativePushEvent event) async {
    await handler?.call(event);
  }

  @override
  Future<void> close() async {
    handler = null;
  }
}

NativePushStatus _authorizedStatus({
  String? token = 'native-token-123456789',
  String provider = 'APNS',
  String platform = 'IOS',
}) {
  return NativePushStatus(
    supported: true,
    platform: platform,
    permission: NotificationPermissionState.authorized,
    provider: provider,
    token: token,
    appVersion: '1.0.0',
    osVersion: 'test-os',
  );
}

void main() {
  test('typed route parser fails closed and never consumes arbitrary URL', () {
    expect(
      PushRouteIntent.parse({
        'version': 1,
        'destination': 'UNKNOWN',
        'url': 'https://evil.example/',
      })?.destination,
      NotificationDestination.home,
    );
    expect(
      PushRouteIntent.parse({
        'version': 999,
        'destination': 'HOME',
      }),
      isNull,
    );
    final memory = PushRouteIntent.parse({
      'version': 1,
      'destination': 'MEMORY',
      'resource_id': '22222222-2222-4222-8222-222222222222',
      'url': 'https://ignored.example/',
    });
    expect(memory?.destination, NotificationDestination.memory);
    expect(
      memory?.resourceId,
      '22222222-2222-4222-8222-222222222222',
    );
    expect(
      PushRouteIntent.parse({
        'version': 1,
        'destination': 'MEMORY',
        'resource_id': 'not-a-uuid',
      })?.destination,
      NotificationDestination.home,
    );
  });

  test('native permission is not requested during initialization', () async {
    final bridge = FakeNativeNotificationBridge(
      const NativePushStatus(
        supported: true,
        platform: 'IOS',
        permission: NotificationPermissionState.notDetermined,
        provider: 'APNS',
      ),
    );
    final service = NotificationClientService(
      api: JiYiApiClient(
        baseUrl: 'https://example.test/v1',
        sessionStore: MemoryAuthSessionStore(),
      ),
      nativeBridge: bridge,
      tokenStore: MemoryNotificationTokenStore(),
    );

    await service.initialize();

    expect(bridge.permissionRequests, 0);
    expect(service.permission, NotificationPermissionState.notDetermined);
  });

  test('token arriving before login waits for authenticated owner', () async {
    final requests = <http.Request>[];
    final sessionStore = MemoryAuthSessionStore();
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: sessionStore,
      httpClient: MockClient((request) async {
        requests.add(request);
        if (request.url.path == '/v1/auth/login') {
          return _loginResponse();
        }
        if (request.url.path == '/v1/notifications/device') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['client_uuid'], 'memory-installation');
          expect(body['provider'], 'APNS');
          expect(body['platform'], 'IOS');
          expect(body['push_token'], 'native-token-123456789');
          return http.Response(
            jsonEncode({
              'id': '33333333-3333-4333-8333-333333333333',
              'client_uuid': 'memory-installation',
              'platform': 'IOS',
              'provider': 'APNS',
              'push_enabled': true,
              'push_token_updated_at': '2026-10-07T00:00:00Z',
              'push_invalidated_at': null,
              'app_version': '1.0.0',
              'os_version': 'test-os',
              'last_active_at': '2026-10-07T00:00:00Z',
            }),
            200,
            headers: _jsonHeaders,
          );
        }
        throw StateError('unexpected request: ${request.method} ${request.url}');
      }),
    );
    final bridge = FakeNativeNotificationBridge(_authorizedStatus());
    final service = NotificationClientService(
      api: api,
      nativeBridge: bridge,
      tokenStore: MemoryNotificationTokenStore(),
    );

    await service.initialize();
    expect(requests, isEmpty);

    await api.login(
      email: 'user@example.test',
      password: 'example-password-123',
    );
    await service.onAuthenticated();

    expect(
      requests.map((request) => request.url.path),
      ['/v1/auth/login', '/v1/notifications/device'],
    );
    expect(service.registration, NotificationRegistrationState.registered);
  });

  test('logout retires server binding before native provider token', () async {
    final requests = <String>[];
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: MemoryAuthSessionStore(),
      httpClient: MockClient((request) async {
        requests.add('${request.method} ${request.url.path}');
        if (request.url.path == '/v1/auth/login') return _loginResponse();
        if (request.method == 'PUT' &&
            request.url.path == '/v1/notifications/device') {
          return http.Response(
            jsonEncode({
              'id': '33333333-3333-4333-8333-333333333333',
              'client_uuid': 'memory-installation',
              'platform': 'IOS',
              'provider': 'APNS',
              'push_enabled': true,
              'push_token_updated_at': '2026-10-07T00:00:00Z',
              'push_invalidated_at': null,
              'app_version': null,
              'os_version': null,
              'last_active_at': null,
            }),
            200,
            headers: _jsonHeaders,
          );
        }
        if (request.method == 'DELETE' &&
            request.url.path == '/v1/notifications/device/memory-installation') {
          return http.Response(
            jsonEncode({
              'id': '33333333-3333-4333-8333-333333333333',
              'client_uuid': 'memory-installation',
              'platform': 'IOS',
              'provider': 'APNS',
              'push_enabled': false,
              'push_token_updated_at': '2026-10-07T00:00:00Z',
              'push_invalidated_at': '2026-10-07T00:01:00Z',
              'app_version': null,
              'os_version': null,
              'last_active_at': null,
            }),
            200,
            headers: _jsonHeaders,
          );
        }
        throw StateError('unexpected request: ${request.method} ${request.url}');
      }),
    );
    final bridge = FakeNativeNotificationBridge(_authorizedStatus());
    final service = NotificationClientService(
      api: api,
      nativeBridge: bridge,
      tokenStore: MemoryNotificationTokenStore(),
    );

    await api.login(
      email: 'user@example.test',
      password: 'example-password-123',
    );
    await service.initialize();
    expect(service.registration, NotificationRegistrationState.registered);

    await service.prepareForLogout();

    expect(requests.last, 'DELETE /v1/notifications/device/memory-installation');
    expect(bridge.unregisterRequests, 1);
    expect(service.registration, NotificationRegistrationState.idle);
  });

  test('token rotation re-registers only current authenticated generation', () async {
    var putCount = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: MemoryAuthSessionStore(),
      httpClient: MockClient((request) async {
        if (request.url.path == '/v1/auth/login') return _loginResponse();
        if (request.method == 'PUT') {
          putCount += 1;
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(
            jsonEncode({
              'id': '33333333-3333-4333-8333-333333333333',
              'client_uuid': body['client_uuid'],
              'platform': body['platform'],
              'provider': body['provider'],
              'push_enabled': true,
              'push_token_updated_at': '2026-10-07T00:00:00Z',
              'push_invalidated_at': null,
              'app_version': null,
              'os_version': null,
              'last_active_at': null,
            }),
            200,
            headers: _jsonHeaders,
          );
        }
        throw StateError('unexpected request');
      }),
    );
    final bridge = FakeNativeNotificationBridge(_authorizedStatus());
    final service = NotificationClientService(
      api: api,
      nativeBridge: bridge,
      tokenStore: MemoryNotificationTokenStore(),
    );
    await api.login(email: 'a@example.test', password: 'password-123456');
    await service.initialize();
    expect(putCount, 1);

    final rotated = _authorizedStatus(token: 'rotated-token-123456789');
    bridge.current = rotated;
    await bridge.emit(NativePushEvent(kind: 'token', status: rotated));

    expect(putCount, 2);
    expect(service.registration, NotificationRegistrationState.registered);
  });

  test('cold start tap queues until route handler and duplicate id is one-shot', () async {
    final bridge = FakeNativeNotificationBridge(
      const NativePushStatus(
        supported: true,
        platform: 'IOS',
        permission: NotificationPermissionState.notDetermined,
        provider: 'APNS',
      ),
    );
    final service = NotificationClientService(
      api: JiYiApiClient(
        baseUrl: 'https://example.test/v1',
        sessionStore: MemoryAuthSessionStore(),
      ),
      nativeBridge: bridge,
      tokenStore: MemoryNotificationTokenStore(),
    );
    await service.initialize();

    final tap = NativePushEvent(
      kind: 'tap',
      eventId: 'tap-1',
      payload: {
        'version': 1,
        'destination': 'FAMILY',
      },
    );
    await bridge.emit(tap);

    final received = <PushRouteIntent>[];
    service.setRouteHandler((intent) async => received.add(intent));
    await Future<void>.delayed(Duration.zero);
    expect(received.map((item) => item.destination), [
      NotificationDestination.family,
    ]);

    await bridge.emit(tap);
    expect(received, hasLength(1));
  });
}
