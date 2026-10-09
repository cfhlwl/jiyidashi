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
import 'package:jiyidashi/wechat_auth_bridge.dart';

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
  Completer<void>? pendingCancel;

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
    if (pendingCancel != null) await pendingCancel!.future;
    return const PhoneOneTapResult.cancelled();
  }

  @override
  Future<PhoneOneTapResult> revokePrivacy() async {
    revokePrivacyCalls += 1;
    return const PhoneOneTapResult.unavailable('PRIVACY_REVOKED');
  }
}

AuthCapabilities _capabilities({
  AuthCapabilityStatus email = AuthCapabilityStatus.available,
  AuthCapabilityStatus phone = AuthCapabilityStatus.disabled,
  AuthCapabilityStatus sms = AuthCapabilityStatus.disabled,
  AuthCapabilityStatus wechat = AuthCapabilityStatus.disabled,
}) {
  return AuthCapabilities.statuses(
    emailStatus: email,
    phoneOneTapStatus: phone,
    smsOtpStatus: sms,
    wechatStatus: wechat,
  );
}

Map<String, dynamic> _sessionResponse() => {
      'access_token': 'access-token',
      'refresh_token': 'refresh-token-abcdefghijklmnopqrstuvwxyz',
      'session_id': 'session-one-tap',
      'user_id': 'user-one-tap',
      'access_expires_at': '2030-01-01T00:00:00Z',
      'account_deletion_in_progress': false,
    };

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
  AuthCapabilityLoader? authCapabilityLoader,
  VoidCallback? onAuthenticated,
  VoidCallback? onSmsOtp,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      home: AuthPage(
        api: api,
        capabilities: capabilities,
        phoneOneTapBridge: bridge,
        authCapabilityLoader: authCapabilityLoader,
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
  test('privacy false fails closed for every non-email capability', () async {
    final bridge = _TestPhoneBridge();
    var loaderCalls = 0;
    final authority = AuthCapabilityAuthority(
      phoneOneTapBridge: bridge,
      serverCapabilityLoader: () async {
        loaderCalls += 1;
        return const AuthCapabilities.allEnabled();
      },
    );

    final capabilities = await authority.probe(
      privacyConsentGranted: false,
      baseline: const AuthCapabilities.allEnabled(),
    );

    expect(capabilities.email, isTrue);
    expect(capabilities.phoneOneTap, isFalse);
    expect(capabilities.smsOtp, isFalse);
    expect(capabilities.wechat, isFalse);
    expect(loaderCalls, 0);
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

  test('phone probe keeps WeChat fail closed without server authority', () async {
    final bridge = _TestPhoneBridge();
    final baseline = _capabilities(
      email: AuthCapabilityStatus.planned,
      phone: AuthCapabilityStatus.disabled,
      sms: AuthCapabilityStatus.planned,
      wechat: AuthCapabilityStatus.unsupported,
    );
    final result = await AuthCapabilityAuthority(
      phoneOneTapBridge: bridge,
    ).probe(privacyConsentGranted: true, baseline: baseline);

    expect(result.emailStatus, AuthCapabilityStatus.planned);
    expect(result.phoneOneTapStatus, AuthCapabilityStatus.available);
    expect(result.smsOtpStatus, AuthCapabilityStatus.planned);
    expect(result.wechatStatus, AuthCapabilityStatus.unavailable);

    final disabledEmail = await AuthCapabilityAuthority(
      phoneOneTapBridge: _TestPhoneBridge(
        availability: const PhoneOneTapResult.providerError('PROVIDER'),
      ),
    ).probe(
      privacyConsentGranted: true,
      baseline: _capabilities(email: AuthCapabilityStatus.unavailable),
    );
    expect(disabledEmail.emailStatus, AuthCapabilityStatus.unavailable);
    expect(disabledEmail.phoneOneTapStatus, AuthCapabilityStatus.unavailable);
  });

  test('WeChat never trusts an injected baseline without server capability', () async {
    final gateway = FakeWechatAuthGateway();
    final result = await AuthCapabilityAuthority(
      wechatAuthGateway: gateway,
    ).probe(
      privacyConsentGranted: true,
      baseline: const AuthCapabilities.allEnabled(),
    );

    expect(result.wechatStatus, AuthCapabilityStatus.unavailable);
    expect(gateway.initializeCalls, 0);
  });

  test('server capability is the authority for SMS visibility', () async {
    final result = await AuthCapabilityAuthority(
      phoneOneTapBridge: _TestPhoneBridge(),
      serverCapabilityLoader: () async => const AuthCapabilities.statuses(
        emailStatus: AuthCapabilityStatus.available,
        phoneOneTapStatus: AuthCapabilityStatus.unavailable,
        smsOtpStatus: AuthCapabilityStatus.available,
        wechatStatus: AuthCapabilityStatus.disabled,
      ),
    ).probe(privacyConsentGranted: true);

    expect(result.email, isTrue);
    expect(result.smsOtp, isTrue);
    expect(result.phoneOneTap, isFalse);
    expect(result.wechat, isFalse);
  });

  test('capability transport failure hides every non-email provider', () async {
    final result = await AuthCapabilityAuthority(
      phoneOneTapBridge: _TestPhoneBridge(),
      serverCapabilityLoader: () async => throw const FormatException('offline'),
    ).probe(
      privacyConsentGranted: true,
      baseline: const AuthCapabilities.allEnabled(),
    );

    expect(result.email, isTrue);
    expect(result.smsOtp, isFalse);
    expect(result.phoneOneTap, isFalse);
    expect(result.wechat, isFalse);
  });

  test('API client parses the provider-neutral capability response', () async {
    final api = _api(
      handler: (request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/v1/auth/capabilities');
        return http.Response(
          jsonEncode({
            'email': 'AVAILABLE',
            'sms_otp': 'AVAILABLE',
            'phone_one_tap': 'UNAVAILABLE',
            'wechat': 'DISABLED',
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      },
    );

    final result = await api.fetchAuthCapabilities();

    expect(result.email, isTrue);
    expect(result.smsOtp, isTrue);
    expect(result.phoneOneTap, isFalse);
    expect(result.wechat, isFalse);
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

  testWidgets('privacy revoke fences a stale capability probe', (tester) async {
    final capabilityResponse = Completer<AuthCapabilities>();
    final api = _api(handler: (_) async => http.Response('{}', 200));

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: _TestPhoneBridge(),
      capabilities: const AuthCapabilities.allEnabled(),
      authCapabilityLoader: () => capabilityResponse.future,
      onSmsOtp: () {},
    );

    final consent = find.byKey(const ValueKey('auth-v3-privacy-consent'));
    await tester.ensureVisible(consent);
    await tester.tap(consent);
    await tester.pump();

    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-sms-fallback')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-register-entry')), findsOneWidget);

    capabilityResponse.complete(const AuthCapabilities.allEnabled());
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-sms-fallback')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-register-entry')), findsOneWidget);
  });

  testWidgets('SMS fallback requires privacy and server capability approval',
      (tester) async {
    final bridge = _TestPhoneBridge();
    final api = _api(handler: (_) async => http.Response('{}', 200));
    var smsAttempts = 0;

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: const AuthCapabilities.emailOnly(),
      authCapabilityLoader: () async => const AuthCapabilities.statuses(
        emailStatus: AuthCapabilityStatus.available,
        phoneOneTapStatus: AuthCapabilityStatus.unavailable,
        smsOtpStatus: AuthCapabilityStatus.available,
        wechatStatus: AuthCapabilityStatus.disabled,
      ),
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
          jsonEncode(_sessionResponse()),
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

  testWidgets('email fallback keeps one-tap disabled during slow native cancel',
      (tester) async {
    final bridge = _TestPhoneBridge(
      loginResult: const PhoneOneTapResult.tokenAcquired('late-token'),
    )
      ..pendingLogin = Completer<PhoneOneTapResult>()
      ..pendingCancel = Completer<void>();
    final api = _api(handler: (_) async => http.Response('{}', 200));

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: _capabilities(phone: AuthCapabilityStatus.available),
    );
    final phone = find.byKey(const ValueKey('auth-v3-phone-one-tap'));
    await tester.tap(phone);
    await tester.pump();
    expect(bridge.requestCalls, 1);

    await tester.tap(find.byKey(const ValueKey('auth-v3-email-fallback')));
    await tester.pump();
    expect(bridge.cancelCalls, 1);
    expect(
      tester.widget<AuthV3PrimaryAction>(phone).onPressed,
      isNull,
    );
    await tester.tap(phone, warnIfMissed: false);
    await tester.pump();
    expect(bridge.requestCalls, 1);

    bridge.pendingCancel!.complete();
    bridge.pendingLogin!.complete(
      const PhoneOneTapResult.tokenAcquired('late-token'),
    );
    await tester.pumpAndSettle();
    expect(find.text('请输入邮箱地址'), findsOneWidget);
  });

  testWidgets('privacy revoke immediately hides one-tap and revokes native state',
      (tester) async {
    final bridge = _TestPhoneBridge();
    final api = _api(handler: (_) async => http.Response('{}', 200));

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: const AuthCapabilities.allEnabled(),
      onSmsOtp: () {},
    );
    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsOneWidget);

    final consent = find.byKey(const ValueKey('auth-v3-privacy-consent'));
    await tester.ensureVisible(consent);
    await tester.tap(consent);
    await tester.pumpAndSettle();

    expect(bridge.revokePrivacyCalls, 1);
    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-sms-fallback')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-register-entry')), findsOneWidget);
    expect(find.text('邮箱登录'), findsOneWidget);
  });

  testWidgets('cancel during exchange fences the late backend session',
      (tester) async {
    final bridge = _TestPhoneBridge(
      loginResult: const PhoneOneTapResult.tokenAcquired('opaque-token'),
    );
    final requestStarted = Completer<void>();
    final response = Completer<http.Response>();
    final store = MemoryAuthSessionStore();
    final api = JiYiApiClient(
      baseUrl: 'https://auth-v3.test/v1',
      httpClient: MockClient((request) async {
        requestStarted.complete();
        return response.future;
      }),
      sessionStore: store,
    );
    var authenticated = 0;

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: _capabilities(phone: AuthCapabilityStatus.available),
      onAuthenticated: () => authenticated += 1,
    );
    await tester.tap(find.byKey(const ValueKey('auth-v3-phone-one-tap')));
    await tester.pump();
    await requestStarted.future;
    final fallback = find.byKey(const ValueKey('auth-v3-email-fallback'));
    await tester.ensureVisible(fallback);
    await tester.tap(fallback);
    await tester.pump();
    expect(bridge.cancelCalls, 1);
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
  });

  testWidgets('privacy revoke during exchange fences the late backend session',
      (tester) async {
    final bridge = _TestPhoneBridge(
      loginResult: const PhoneOneTapResult.tokenAcquired('opaque-token'),
    );
    final requestStarted = Completer<void>();
    final response = Completer<http.Response>();
    final store = MemoryAuthSessionStore();
    final api = JiYiApiClient(
      baseUrl: 'https://auth-v3.test/v1',
      httpClient: MockClient((request) async {
        requestStarted.complete();
        return response.future;
      }),
      sessionStore: store,
    );

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: _capabilities(phone: AuthCapabilityStatus.available),
    );
    await tester.tap(find.byKey(const ValueKey('auth-v3-phone-one-tap')));
    await requestStarted.future;
    final consent = find.byKey(const ValueKey('auth-v3-privacy-consent'));
    await tester.ensureVisible(consent);
    await tester.tap(consent);
    await tester.pump();
    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-sms-fallback')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-register-entry')), findsOneWidget);
    response.complete(
      http.Response(
        jsonEncode(_sessionResponse()),
        200,
        headers: {'content-type': 'application/json'},
      ),
    );
    await tester.pumpAndSettle();

    expect(api.authenticatedUserId, isNull);
    expect(api.accessToken, isNull);
    expect(api.authenticatedSessionId, isNull);
    expect(store.session, isNull);
  });

  testWidgets('privacy revoke hides capability before slow native cancel completes',
      (tester) async {
    final bridge = _TestPhoneBridge(
      loginResult: const PhoneOneTapResult.tokenAcquired('opaque-token'),
    )..pendingLogin = Completer<PhoneOneTapResult>();
    final cancelDone = Completer<void>();
    bridge.pendingCancel = cancelDone;
    final api = _api(handler: (_) async => http.Response('{}', 200));

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: _capabilities(phone: AuthCapabilityStatus.available),
    );
    await tester.tap(find.byKey(const ValueKey('auth-v3-phone-one-tap')));
    await tester.pump();
    final consent = find.byKey(const ValueKey('auth-v3-privacy-consent'));
    await tester.ensureVisible(consent);
    await tester.tap(consent);
    await tester.pump();

    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsNothing);
    expect(bridge.cancelCalls, 1);
    expect(bridge.requestCalls, 1);

    cancelDone.complete();
    bridge.pendingLogin!.complete(
      const PhoneOneTapResult.tokenAcquired('late-token'),
    );
    await tester.pumpAndSettle();
    expect(find.text('late-token'), findsNothing);
  });

  testWidgets('phone-only capability renders without email controls',
      (tester) async {
    final bridge = _TestPhoneBridge();
    final api = _api(handler: (_) async => http.Response('{}', 200));
    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: _capabilities(
        email: AuthCapabilityStatus.disabled,
        phone: AuthCapabilityStatus.available,
      ),
    );

    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsOneWidget);
    expect(find.byKey(const ValueKey('auth-v3-email-fallback')), findsNothing);
    expect(find.byType(TextField), findsNothing);
    expect(find.text('邮箱登录'), findsNothing);
  });

  testWidgets('SMS-only capability renders its callback seam', (tester) async {
    final bridge = _TestPhoneBridge();
    final api = _api(handler: (_) async => http.Response('{}', 200));
    var smsAttempts = 0;
    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      capabilities: const AuthCapabilities.statuses(
        emailStatus: AuthCapabilityStatus.disabled,
      ),
      authCapabilityLoader: () async => const AuthCapabilities.statuses(
        emailStatus: AuthCapabilityStatus.disabled,
        phoneOneTapStatus: AuthCapabilityStatus.unavailable,
        smsOtpStatus: AuthCapabilityStatus.available,
        wechatStatus: AuthCapabilityStatus.disabled,
      ),
      onSmsOtp: () => smsAttempts += 1,
    );

    expect(find.byKey(const ValueKey('auth-v3-sms-fallback')), findsOneWidget);
    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsNothing);
    expect(find.byType(TextField), findsNothing);
    expect(find.text('邮箱登录'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('auth-v3-sms-fallback')));
    expect(smsAttempts, 1);
  });

  testWidgets('privacy false cold start hides injected non-email capabilities',
      (tester) async {
    final bridge = _TestPhoneBridge();
    final api = _api(handler: (_) async => http.Response('{}', 200));
    var loaderCalls = 0;
    var smsAttempts = 0;

    await _pumpAuthPage(
      tester,
      api: api,
      bridge: bridge,
      privacyConsentGranted: false,
      capabilities: const AuthCapabilities.allEnabled(),
      authCapabilityLoader: () async {
        loaderCalls += 1;
        return const AuthCapabilities.statuses(
          emailStatus: AuthCapabilityStatus.available,
          phoneOneTapStatus: AuthCapabilityStatus.unavailable,
          smsOtpStatus: AuthCapabilityStatus.available,
          wechatStatus: AuthCapabilityStatus.disabled,
        );
      },
      onSmsOtp: () => smsAttempts += 1,
    );

    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-sms-fallback')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-register-entry')), findsOneWidget);
    expect(find.text('邮箱登录'), findsOneWidget);
    expect(loaderCalls, 0);
    expect(bridge.initializeCalls, 0);
    expect(bridge.checkAvailabilityCalls, 0);

    await tester.tap(find.byKey(const ValueKey('auth-v3-privacy-consent')));
    await tester.pumpAndSettle();

    expect(loaderCalls, 1);
    expect(find.byKey(const ValueKey('auth-v3-sms-fallback')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('auth-v3-sms-fallback')));
    expect(smsAttempts, 1);
  });

  testWidgets('all unavailable capabilities render the neutral empty state',
      (tester) async {
    final api = _api(handler: (_) async => http.Response('{}', 200));
    await _pumpAuthPage(
      tester,
      api: api,
      bridge: _TestPhoneBridge(),
      privacyConsentGranted: false,
      capabilities: _capabilities(email: AuthCapabilityStatus.disabled),
    );

    expect(find.text('当前暂时没有可用的登录方式'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-phone-one-tap')), findsNothing);
    expect(find.byKey(const ValueKey('auth-v3-sms-fallback')), findsNothing);
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
