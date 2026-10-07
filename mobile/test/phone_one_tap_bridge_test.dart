import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';
import 'package:jiyidashi/phone_one_tap_bridge.dart';

const _jsonHeaders = {'content-type': 'application/json'};

Map<String, dynamic> _sessionPayload() => {
      'access_token': 'access-phone-one-tap',
      'refresh_token': 'refresh-phone-one-tap-abcdefghijklmnopqrstuvwxyz',
      'session_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      'token_type': 'bearer',
      'user_id': '11111111-1111-4111-8111-111111111111',
      'access_expires_at': '2030-09-30T00:15:00Z',
      'refresh_expires_at': '2030-10-30T00:00:00Z',
      'account_deletion_in_progress': false,
    };

class _FakeExchangeClient implements PhoneOneTapExchangeClient {
  _FakeExchangeClient({this.failFirst = false});

  final bool failFirst;
  final calls = <Map<String, String>>[];

  @override
  Future<String> canonicalClientUuid() async => 'installation-a';

  @override
  Future<void> exchangePhoneOneTap({
    required String loginToken,
    required String requestId,
    required String deviceId,
    String? clientPlatform,
    String? deviceName,
  }) async {
    calls.add({
      'login_token': loginToken,
      'request_id': requestId,
      'device_id': deviceId,
    });
    if (failFirst && calls.length == 1) {
      throw TransportException('网络响应丢失');
    }
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('method channel translates only JiYi states and opaque token', () async {
    final channel = const MethodChannel('cn.jiyidashi/phone_one_tap');
    final calls = <String>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      calls.add(call.method);
      if (call.method == 'requestLoginToken') {
        return <String, Object?>{
          'state': 'TOKEN_ACQUIRED',
          'login_token': 'opaque-token',
        };
      }
      return <String, Object?>{'state': 'AVAILABLE'};
    });
    addTearDown(() {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, null);
    });

    final bridge = MethodChannelPhoneOneTapBridge(channel: channel);
    expect(
      (await bridge.initialize(privacyConsentGranted: true)).state,
      PhoneOneTapState.available,
    );
    final token = await bridge.requestLoginToken();

    expect(token.state, PhoneOneTapState.tokenAcquired);
    expect(token.loginToken, 'opaque-token');
    expect(calls, ['initialize', 'requestLoginToken']);
  });

  test('privacy gate returns unavailable without invoking provider', () async {
    final bridge = FakePhoneOneTapBridge(
      initializeResult: const PhoneOneTapResult.available(),
    );

    final result = await bridge.initialize(privacyConsentGranted: false);

    expect(result.state, PhoneOneTapState.unavailable);
    expect(result.reason, 'PRIVACY_NOT_ACCEPTED');
  });

  test('native states and token success stay provider-neutral', () async {
    final bridge = FakePhoneOneTapBridge(
      loginResult: const PhoneOneTapResult.tokenAcquired('opaque-token'),
    );

    final result = await bridge.requestLoginToken();

    expect(result.state, PhoneOneTapState.tokenAcquired);
    expect(result.loginToken, 'opaque-token');
    expect(result.toString(), isNot(contains('opaque-token')));
    expect(bridge.requestLoginTokenCalls, 1);
  });

  test('response-loss retry reuses the same request id and token in memory', () async {
    final bridge = FakePhoneOneTapBridge(
      loginResult: const PhoneOneTapResult.tokenAcquired('opaque-token'),
    );
    final client = _FakeExchangeClient(failFirst: true);
    final coordinator = PhoneOneTapLoginCoordinator(
      bridge: bridge,
      exchangeClient: client,
    );

    final attempt = await coordinator.requestAttempt();
    await expectLater(coordinator.exchange(attempt), throwsA(isA<TransportException>()));
    await coordinator.exchange(attempt);

    expect(client.calls, hasLength(2));
    expect(client.calls[0], client.calls[1]);
    expect(attempt.requestId, matches(RegExp(r'^[0-9a-f-]{36}$')));
    expect(attempt.toString(), isNot(contains('opaque-token')));
  });

  test('backend exchange persists only the existing JiYi session shape', () async {
    final store = MemoryAuthSessionStore()..installationId = 'installation-a';
    Map<String, dynamic>? body;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        body = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(jsonEncode(_sessionPayload()), 200, headers: _jsonHeaders);
      }),
    );

    await api.exchangePhoneOneTap(
      loginToken: 'opaque-token',
      requestId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      deviceId: 'installation-a',
    );

    expect(body, isNotNull);
    expect(body!.keys, containsAll(<String>[
      'login_token',
      'request_id',
      'device_id',
    ]));
    expect(body!.keys, isNot(contains('phone')));
    expect(body!.keys, isNot(contains('mobile')));
    expect(body!.keys, isNot(contains('masked_phone')));
    expect(store.session!.toJson(), {
      'refresh_token': 'refresh-phone-one-tap-abcdefghijklmnopqrstuvwxyz',
      'session_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    });
  });

  test('provider token is not exposed by persisted session or diagnostics', () async {
    final store = MemoryAuthSessionStore();
    final result = const PhoneOneTapResult.tokenAcquired('secret-provider-token');

    expect(result.toString(), isNot(contains('secret-provider-token')));
    expect(store.session, isNull);
    expect(store.installationId, isNull);
  });

  for (final status in <int>[401, 409, 429, 502, 503, 504]) {
    test('backend status $status remains a stable ApiException', () async {
      final api = JiYiApiClient(
        baseUrl: 'https://example.test/v1',
        httpClient: MockClient((_) async {
          return http.Response(
            jsonEncode({'detail': 'AUTH_PHONE_ONE_TAP_PROVIDER_ERROR'}),
            status,
            headers: _jsonHeaders,
          );
        }),
      );

      await expectLater(
        api.exchangePhoneOneTap(
          loginToken: 'opaque-token',
          requestId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          deviceId: 'installation-a',
        ),
        throwsA(
          isA<ApiException>()
              .having((error) => error.statusCode, 'statusCode', status),
        ),
      );
    });
  }
}
