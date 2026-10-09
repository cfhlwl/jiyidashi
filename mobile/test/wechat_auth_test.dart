import 'dart:async';

import 'package:flutter/material.dart';
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

  @override
  Future<WechatAuthResult> initialize({required bool privacyConsentGranted}) =>
      Future.value(const WechatAuthResult.available());

  @override
  Future<WechatAuthResult> checkAvailability() =>
      Future.value(const WechatAuthResult.available());

  @override
  Future<WechatAuthResult> requestCredential() => credential.future;

  @override
  Future<WechatAuthResult> cancel() async {
    cancelCalls += 1;
    return const WechatAuthResult.cancelled();
  }

  @override
  Future<WechatAuthResult> revokePrivacy() =>
      Future.value(const WechatAuthResult.unavailable('PRIVACY_REVOKED'));
}

JiYiApiClient _api() => JiYiApiClient(
  sessionStore: MemoryAuthSessionStore()..installationId = 'wechat-test',
  httpClient: MockClient((_) async => http.Response('{}', 200)),
  baseUrl: 'https://auth.test/v1',
);

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
  });
}
