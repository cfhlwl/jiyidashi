import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';
import 'package:jiyidashi/auth_v3.dart';
import 'package:jiyidashi/phone_one_tap_bridge.dart';
import 'package:jiyidashi/stage1_app.dart';

class _TestPhoneBridge implements PhoneOneTapBridge {
  _TestPhoneBridge({
    this.availability = const PhoneOneTapResult.available(),
    this.loginResult = const PhoneOneTapResult.cancelled(),
  });

  PhoneOneTapResult availability;
  PhoneOneTapResult loginResult;
  int initializeCalls = 0;
  int checkAvailabilityCalls = 0;
  int cancelCalls = 0;
  int revokePrivacyCalls = 0;
  int requestCalls = 0;
  Completer<PhoneOneTapResult>? pendingLogin;

  @override
  Future<PhoneOneTapResult> initialize({
    required bool privacyConsentGranted,
  }) async {
    initializeCalls += 1;
    return privacyConsentGranted
        ? availability
        : const PhoneOneTapResult.unavailable('PRIVACY_REVOKED');
  }

  @override
  Future<PhoneOneTapResult> checkAvailability() async {
    checkAvailabilityCalls += 1;
    return availability;
  }

  @override
  Future<PhoneOneTapResult> preLogin() async => availability;

  @override
  Future<PhoneOneTapResult> requestLoginToken() {
    requestCalls += 1;
    return pendingLogin?.future ?? Future<PhoneOneTapResult>.value(loginResult);
  }

  @override
  Future<PhoneOneTapResult> cancel() async {
    cancelCalls += 1;
    return const PhoneOneTapResult.cancelled();
  }

  @override
  Future<PhoneOneTapResult> revokePrivacy() async {
    revokePrivacyCalls += 1;
    return const PhoneOneTapResult.unavailable('PRIVACY_REVOKED');
  }
}

AuthCapabilities _capabilities({
  AuthCapabilityStatus phone = AuthCapabilityStatus.disabled,
  AuthCapabilityStatus sms = AuthCapabilityStatus.disabled,
}) {
  return AuthCapabilities.statuses(
    emailStatus: AuthCapabilityStatus.available,
    phoneOneTapStatus: phone,
    smsOtpStatus: sms,
  );
}

JiYiApiClient _api({
  required Future<http.Response> Function(http.Request) handler,
}) {
  return JiYiApiClient(
    baseUrl: 'https://auth-v3.test/v1',
    httpClient: MockClient(handler),
    sessionStore: MemoryAuthSessionStore(),
  );
}

Future<void> _pumpAuthPage(
  WidgetTester tester, {
  required JiYiApiClient api,
  required PhoneOneTapBridge bridge,
  required AuthCapabilities capabilities,
  bool privacyConsentGranted = true,
  VoidCallback? onAuthenticated,
  VoidCallback? onSmsOtp,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      home: AuthPage(
        api: api,
        capabilities: capabilities,
        phoneOneTapBridge: bridge,
        privacyConsentGranted: privacyConsentGranted,
        onAuthenticated: onAuthenticated ?? () {},
        onSmsOtp: onSmsOtp,
      ),
    ),
  );
  await tester.pump();
  await tester.pump();
}

void main() {
  test('capability authority is email-only before privacy consent', () async {
    final bridge = _TestPhoneBridge();
    final authority = AuthCapabilityAuthority(phoneOneTapBridge: bridge);

    final capabilities = await authority.probe(privacyConsentGranted: false);

    expect(capabilities.email, isTrue);
    expect(capabilities.phoneOneTap, isFalse);
    expect(bridge.initializeCalls, 0);
    expect(bridge.checkAvailabilityCalls, 0);
  });

  test('capability authority maps available and provider failure states', () async {
    final availableBridge = _TestPhoneBridge();
    final available = await AuthCapabilityAuthority(
      phoneOneTapBridge: availableBridge,
    ).probe(privacyConsentGranted: true);
    expect(available.phoneOneTap, isTrue);
    expect(available.status(AuthV3Provider.phoneOneTap),
        AuthCapabilityStatus.available);

    final unavailableBridge = _TestPhoneBridge(
      availability: const PhoneOneTapResult.unavailable('UNSUPPORTED'),
    );
    final unavailable = await AuthCapabilityAuthority(
      phoneOneTapBridge: unavailableBridge,
    ).probe(privacyConsentGranted: true);
    expect(unavailable.phoneOneTap, isFalse);
    expect(unavailable.status(AuthV3Provider.phoneOneTap),
        AuthCapabilityStatus.unavailable);
  });

  test('capability statuses keep planned and disabled providers hidden', () {
    const capabilities = AuthCapabilities.statuses(
      emailStatus: AuthCapabilityStatus.available,
      phoneOneTapStatus: AuthCapabilityStatus.planned,
      smsOtpStatus: AuthCapabilityStatus.disabled,
      wechatStatus: AuthCapabilityStatus.unsupported,
    );

    expect(capabilities.email, isTrue);
    expect(capabilities.phoneOneTap, isFalse);
    expect(capabilities.smsOtp, isFalse);
    expect(capabilities.wechat, isFalse);
  });

  testWidgets('SMS fallback remains capability-gated and invokes its callback',
      (tester) async {
    final bridge = _TestPhoneBridge();
    final api = _api(handler: (_) async => http.Response('{}', 200));
    var smsAttempts = 0;

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      privacyConsentGranted: false,
      capabilities: _capabilities(sms: AuthCapabilityStatus.available),
      onSmsOtp: () => smsAttempts += 1,
    );

    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-sms-fallback')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('auth-v3-sms-fallback')));
    expect(smsAttempts, 1);
  });

  testWidgets('available one-tap is visible and exchanges a transient token',
      (tester) async {
    final bridge = _TestPhoneBridge(
      loginResult: const PhoneOneTapResult.tokenAcquired('opaque-token'),
    );
    final requests = <http.Request>[];
    var authenticated = 0;
    final api = _api(
      handler: (request) async {
        requests.add(request);
        return http.Response(
          jsonEncode({
            'access_token': 'access-token',
            'refresh_token': 'refresh-token-abcdefghijklmnopqrstuvwxyz',
            'session_id': 'session-one-tap',
            'user_id': 'user-one-tap',
            'access_expires_at': '2030-01-01T00:00:00Z',
            'account_deletion_in_progress': false,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      },
    );

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: _capabilities(phone: AuthCapabilityStatus.available),
      onAuthenticated: () => authenticated += 1,
    );
    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsOneWidget);
    expect(find.text('opaque-token'), findsNothing);

    await tester.tap(find.byKey(const ValueKey('auth-v3-phone-one-tap')));
    await tester.pumpAndSettle();

    expect(authenticated, 1);
    expect(bridge.requestCalls, 1);
    expect(requests, hasLength(1));
    final body = jsonDecode(requests.single.body) as Map<String, dynamic>;
    expect(body.keys, isNot(contains('phone')));
    expect(body.keys, isNot(contains('mobile')));
    expect(body.keys, isNot(contains('masked_phone')));
  });

  testWidgets('unavailable one-tap keeps email usable and hides provider',
      (tester) async {
    final bridge = _TestPhoneBridge(
      availability: const PhoneOneTapResult.unavailable('UNSUPPORTED'),
    );
    final api = _api(
      handler: (_) async => http.Response('{}', 200),
    );

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: _capabilities(),
    );

    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-register-entry')), findsOneWidget);
    expect(find.text('邮箱登录'), findsOneWidget);
  });

  testWidgets('double tap creates one native request and email switch cancels',
      (tester) async {
    final bridge = _TestPhoneBridge(
      loginResult: const PhoneOneTapResult.tokenAcquired('late-token'),
    )..pendingLogin = Completer<PhoneOneTapResult>();
    final api = _api(handler: (_) async => http.Response('{}', 200));

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: _capabilities(phone: AuthCapabilityStatus.available),
    );
    final button = find.byKey(const ValueKey('auth-v3-phone-one-tap'));
    await tester.tap(button);
    await tester.pump();
    await tester.tap(button);
    expect(bridge.requestCalls, 1);

    await tester.tap(find.byKey(const ValueKey('auth-v3-email-fallback')));
    await tester.pump();
    expect(bridge.cancelCalls, 1);
    bridge.pendingLogin!.complete(
      const PhoneOneTapResult.tokenAcquired('late-token'),
    );
    await tester.pumpAndSettle();
    expect(find.text('late-token'), findsNothing);
  });

  testWidgets('privacy revoke immediately hides one-tap and revokes native state',
      (tester) async {
    final bridge = _TestPhoneBridge();
    final api = _api(handler: (_) async => http.Response('{}', 200));

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: _capabilities(phone: AuthCapabilityStatus.available),
    );
    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('auth-v3-privacy-consent')));
    await tester.pumpAndSettle();

    expect(bridge.revokePrivacyCalls, 1);
    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsNothing);
    expect(find.text('邮箱登录'), findsOneWidget);
  });

  testWidgets('provider error exposes consumer-safe fallback only', (tester) async {
    final bridge = _TestPhoneBridge(
      loginResult: const PhoneOneTapResult.providerError('ALIYUN_RAW_500'),
    );
    final api = _api(handler: (_) async => http.Response('{}', 200));

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: _capabilities(phone: AuthCapabilityStatus.available),
    );
    await tester.tap(find.byKey(const ValueKey('auth-v3-phone-one-tap')));
    await tester.pumpAndSettle();

    expect(find.text('ALIYUN_RAW_500'), findsNothing);
    expect(find.text('本机号码登录暂时不可用，请使用邮箱登录。'), findsOneWidget);
  });

  testWidgets('cancelled and timeout states remain consumer-safe', (tester) async {
    for (final result in <PhoneOneTapResult>[
      const PhoneOneTapResult.cancelled(),
      const PhoneOneTapResult.timeout(),
    ]) {
      final bridge = _TestPhoneBridge(loginResult: result);
      final api = _api(handler: (_) async => http.Response('{}', 200));

      await _pumpAuthPage(
        tester,
        api: api,
        bridge: bridge,
        capabilities: _capabilities(phone: AuthCapabilityStatus.available),
      );
      await tester.tap(find.byKey(const ValueKey('auth-v3-phone-one-tap')));
      await tester.pumpAndSettle();

      expect(find.text('opaque-token'), findsNothing);
      expect(find.textContaining('ALIYUN'), findsNothing);
      if (result.state == PhoneOneTapState.cancelled) {
        expect(find.text('本机号码登录响应超时，请使用邮箱登录。'), findsNothing);
      } else {
        expect(find.text('本机号码登录响应超时，请使用邮箱登录。'), findsOneWidget);
      }

      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
    }
  });
}
