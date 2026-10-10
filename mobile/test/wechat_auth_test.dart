import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';
import 'package:jiyidashi/auth_v3.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:jiyidashi/wechat_auth_bridge.dart';

class _ExchangeFake implements WechatExchangeClient {
  int calls = 0;

  @override
  Future<String> canonicalClientUuid() async => 'wechat-installation';

  @override
  Future<void> exchangeWechatCredential({
    required String credential,
    required String requestId,
    required String deviceId,
    String? clientPlatform,
    String? deviceName,
  }) async {
    calls += 1;
  }
}

class _DelayedGateway implements WechatAuthGateway {
  final credential = Completer<WechatAuthResult>();
  int cancelCalls = 0;
  int revokePrivacyCalls = 0;
  int requestCredentialCalls = 0;

  @override
  Future<WechatAuthResult> initialize({required bool privacyConsentGranted}) =>
      Future.value(const WechatAuthResult.available());

  @override
  Future<WechatAuthResult> checkAvailability() =>
      Future.value(const WechatAuthResult.available());

  @override
  Future<WechatAuthResult> requestCredential() {
    requestCredentialCalls += 1;
    return credential.future;
  }

  @override
  Future<WechatAuthResult> cancel() async {
    cancelCalls += 1;
    return const WechatAuthResult.cancelled();
  }

  @override
  Future<WechatAuthResult> revokePrivacy() async {
    revokePrivacyCalls += 1;
    return const WechatAuthResult.unavailable('PRIVACY_REVOKED');
  }
}

class _FailingRevokeGateway extends FakeWechatAuthGateway {
  @override
  Future<WechatAuthResult> revokePrivacy() async {
    revokePrivacyCalls += 1;
    throw StateError('native cleanup failed');
  }
}

JiYiApiClient _api() => JiYiApiClient(
  sessionStore: MemoryAuthSessionStore()..installationId = 'wechat-test',
  httpClient: MockClient((_) async => http.Response('{}', 200)),
  baseUrl: 'https://auth.test/v1',
);

Map<String, dynamic> _sessionResponse() => {
  'access_token': 'wechat-access-token',
  'refresh_token': 'wechat-refresh-token-abcdefghijklmnopqrstuvwxyz',
  'session_id': 'wechat-session',
  'user_id': 'wechat-user',
  'access_expires_at': '2030-01-01T00:00:00Z',
  'account_deletion_in_progress': false,
};

Widget _page({
  required WechatAuthGateway gateway,
  bool privacy = true,
  AuthCapabilityLoader? loader,
}) {
  return MaterialApp(
    home: AuthPage(
      api: _api(),
      capabilities: const AuthCapabilities.allEnabled(),
      privacyConsentGranted: privacy,
      wechatAuthGateway: gateway,
      authCapabilityLoader:
          loader ?? () async => const AuthCapabilities.allEnabled(),
      onAuthenticated: () {},
    ),
  );
}

void main() {
  test('MethodChannel WeChat contract maps native states without leaking code', () async {
    final channel = MethodChannel('cn.jiyidashi/wechat_auth');
    final methods = <String>[];
    final binaryMessenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    binaryMessenger.setMockMethodCallHandler(channel, (call) async {
      methods.add(call.method);
      return switch (call.method) {
        'initialize' => <String, Object?>{'state': 'AVAILABLE'},
        'checkAvailability' => <String, Object?>{'state': 'AVAILABLE'},
        'requestCredential' => <String, Object?>{
            'state': 'CREDENTIAL_ACQUIRED',
            'credential': 'short-lived-code',
          },
        'cancel' => <String, Object?>{'state': 'CANCELLED'},
        'revokePrivacy' => <String, Object?>{
            'state': 'UNAVAILABLE',
            'reason': 'PRIVACY_REVOKED',
          },
        _ => <String, Object?>{'state': 'UNAVAILABLE'},
      };
    });
    addTearDown(() => binaryMessenger.setMockMethodCallHandler(channel, null));

    final gateway = MethodChannelWechatAuthGateway(channel: channel);
    expect(
      (await gateway.initialize(privacyConsentGranted: true)).state,
      WechatAuthState.available,
    );
    expect((await gateway.checkAvailability()).state, WechatAuthState.available);
    final credential = await gateway.requestCredential();
    expect(credential.state, WechatAuthState.credentialAcquired);
    expect(credential.credential, 'short-lived-code');
    expect((await gateway.cancel()).state, WechatAuthState.cancelled);
    expect((await gateway.revokePrivacy()).state, WechatAuthState.unavailable);
    expect(methods, [
      'initialize',
      'checkAvailability',
      'requestCredential',
      'cancel',
      'revokePrivacy',
    ]);
    expect(credential.toString(), isNot(contains('short-lived-code')));
  });

  test('provider-neutral coordinator keeps credential transient', () async {
    final gateway = FakeWechatAuthGateway();
    final exchange = _ExchangeFake();
    final coordinator = WechatLoginCoordinator(
      gateway: gateway,
      exchangeClient: exchange,
    );

    final attempt = await coordinator.requestAttempt();
    expect(attempt.requestId, matches(RegExp(r'^[0-9a-f-]{36}$')));
    await coordinator.exchange(attempt);
    expect(gateway.requestCredentialCalls, 1);
    expect(exchange.calls, 1);
    expect(attempt.toString(), isNot(contains('test-credential')));
  });

  testWidgets('privacy false never flashes WeChat and does not probe native', (
    tester,
  ) async {
    final gateway = FakeWechatAuthGateway();
    var loaderCalls = 0;
    await tester.pumpWidget(
      _page(
        gateway: gateway,
        privacy: false,
        loader: () async {
          loaderCalls += 1;
          return const AuthCapabilities.allEnabled();
        },
      ),
    );
    expect(find.byKey(const ValueKey('auth-v3-wechat-login')), findsNothing);
    expect(gateway.initializeCalls, 0);
    expect(loaderCalls, 0);
    expect(find.text('邮箱登录'), findsOneWidget);
  });

  testWidgets('late credential after privacy revoke cannot exchange', (
    tester,
  ) async {
    final gateway = _DelayedGateway();
    final api = _api();
    await tester.pumpWidget(
      MaterialApp(
        home: AuthPage(
          api: api,
          capabilities: const AuthCapabilities.allEnabled(),
          privacyConsentGranted: true,
          wechatAuthGateway: gateway,
          authCapabilityLoader: () async => const AuthCapabilities.allEnabled(),
          onAuthenticated: () {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    final action = find.byKey(const ValueKey('auth-v3-wechat-login'));
    expect(action, findsOneWidget);
    await tester.tap(action);
    await tester.pump();
    final consent = find.byKey(const ValueKey('auth-v3-privacy-consent'));
    await tester.ensureVisible(consent);
    await tester.tap(consent);
    await tester.pump();
    gateway.credential.complete(
      const WechatAuthResult.credentialAcquired('late'),
    );
    await tester.pump();
    expect(gateway.cancelCalls, 1);
    expect(gateway.revokePrivacyCalls, 1);
  });

  testWidgets('cold start hides injected WeChat until server and native pass', (
    tester,
  ) async {
    final gateway = FakeWechatAuthGateway();
    final capabilityResponse = Completer<AuthCapabilities>();
    await tester.pumpWidget(
      _page(
        gateway: gateway,
        loader: () => capabilityResponse.future,
      ),
    );

    expect(find.byKey(const ValueKey('auth-v3-wechat-login')), findsNothing);
    capabilityResponse.complete(const AuthCapabilities.allEnabled());
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('auth-v3-wechat-login')), findsOneWidget);
    expect(gateway.initializeCalls, 1);
    expect(gateway.checkAvailabilityCalls, 1);
  });

  testWidgets('privacy revoke calls WeChat cleanup with no pending request', (
    tester,
  ) async {
    final gateway = FakeWechatAuthGateway();
    await tester.pumpWidget(_page(gateway: gateway));
    await tester.pumpAndSettle();

    final consent = find.byKey(const ValueKey('auth-v3-privacy-consent'));
    await tester.ensureVisible(consent);
    await tester.tap(consent);
    await tester.pumpAndSettle();

    expect(gateway.revokePrivacyCalls, 1);
    expect(find.byKey(const ValueKey('auth-v3-wechat-login')), findsNothing);
  });

  testWidgets('privacy revoke cleanup failure remains fail closed', (tester) async {
    final gateway = _FailingRevokeGateway();
    await tester.pumpWidget(_page(gateway: gateway));
    await tester.pumpAndSettle();

    final consent = find.byKey(const ValueKey('auth-v3-privacy-consent'));
    await tester.ensureVisible(consent);
    await tester.tap(consent);
    await tester.pumpAndSettle();

    expect(gateway.revokePrivacyCalls, 1);
    expect(find.byKey(const ValueKey('auth-v3-wechat-login')), findsNothing);
    expect(find.text('邮箱登录'), findsOneWidget);
  });

  testWidgets('double tap starts one WeChat native request', (tester) async {
    final gateway = _DelayedGateway();
    await tester.pumpWidget(_page(gateway: gateway));
    await tester.pumpAndSettle();

    final action = find.byKey(const ValueKey('auth-v3-wechat-login'));
    await tester.tap(action);
    await tester.pump();
    await tester.tap(action, warnIfMissed: false);
    await tester.pump();

    expect(gateway.requestCredentialCalls, 1);
    gateway.credential.complete(const WechatAuthResult.cancelled());
    await tester.pumpAndSettle();
  });

  testWidgets('privacy revoke during backend exchange fences late session', (
    tester,
  ) async {
    final gateway = FakeWechatAuthGateway();
    final responseStarted = Completer<void>();
    final response = Completer<http.Response>();
    final store = MemoryAuthSessionStore();
    final api = JiYiApiClient(
      sessionStore: store,
      baseUrl: 'https://auth.test/v1',
      httpClient: MockClient((request) async {
        responseStarted.complete();
        return response.future;
      }),
    );
    var authenticated = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: AuthPage(
          api: api,
          capabilities: const AuthCapabilities.allEnabled(),
          privacyConsentGranted: true,
          wechatAuthGateway: gateway,
          authCapabilityLoader: () async => const AuthCapabilities.allEnabled(),
          onAuthenticated: () => authenticated += 1,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('auth-v3-wechat-login')));
    await responseStarted.future;

    final consent = find.byKey(const ValueKey('auth-v3-privacy-consent'));
    await tester.ensureVisible(consent);
    await tester.tap(consent);
    await tester.pump();
    response.complete(
      http.Response(
        jsonEncode(_sessionResponse()),
        200,
        headers: {'content-type': 'application/json'},
      ),
    );
    await tester.pumpAndSettle();

    expect(authenticated, 0);
    expect(api.authenticatedUserId, isNull);
    expect(api.accessToken, isNull);
    expect(api.authenticatedSessionId, isNull);
    expect(store.session, isNull);
    expect(gateway.revokePrivacyCalls, 1);
  });

  testWidgets('disposing AuthPage fences a late native credential', (tester) async {
    final gateway = _DelayedGateway();
    final exchange = _ExchangeFake();
    await tester.pumpWidget(
      MaterialApp(
        home: AuthPage(
          api: _api(),
          capabilities: const AuthCapabilities.allEnabled(),
          privacyConsentGranted: true,
          wechatAuthGateway: gateway,
          authCapabilityLoader: () async => const AuthCapabilities.allEnabled(),
          onAuthenticated: () {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('auth-v3-wechat-login')));
    await tester.pump();
    await tester.pumpWidget(const SizedBox.shrink());
    gateway.credential.complete(
      const WechatAuthResult.credentialAcquired('late-wechat-credential'),
    );
    await tester.pumpAndSettle();

    expect(gateway.cancelCalls, 1);
    expect(exchange.calls, 0);
  });

  testWidgets('raw WeChat provider error stays consumer safe', (tester) async {
    final gateway = FakeWechatAuthGateway();
    final api = JiYiApiClient(
      sessionStore: MemoryAuthSessionStore(),
      baseUrl: 'https://auth.test/v1',
      httpClient: MockClient(
        (_) async => http.Response(
          jsonEncode({'detail': 'WECHAT_RAW_PROVIDER_SECRET'}),
          502,
          headers: {'content-type': 'application/json'},
        ),
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: AuthPage(
          api: api,
          capabilities: const AuthCapabilities.allEnabled(),
          privacyConsentGranted: true,
          wechatAuthGateway: gateway,
          authCapabilityLoader: () async => const AuthCapabilities.allEnabled(),
          onAuthenticated: () {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('auth-v3-wechat-login')));
    await tester.pumpAndSettle();

    expect(find.text('WECHAT_RAW_PROVIDER_SECRET'), findsNothing);
    expect(find.text('暂时无法完成微信登录，请使用邮箱登录。'), findsOneWidget);
  });
}
