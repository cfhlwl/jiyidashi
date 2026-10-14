import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/account_security_page.dart';
import 'package:jiyidashi/api_client.dart';

const _candidateMode = bool.fromEnvironment(
  'AUTH_006_ACCOUNT_SECURITY_CANDIDATE',
  defaultValue: false,
);
const _canvasKey = ValueKey<String>('auth-006-account-security-canvas');
const _headers = {'content-type': 'application/json'};
const _userId = '11111111-1111-4111-8111-111111111111';
const _sessionId = '22222222-2222-4222-8222-222222222222';

Map<String, dynamic> _token() => {
      'access_token': 'visual-access-token',
      'refresh_token': 'visual-refresh-token-long-enough-1234567890',
      'session_id': _sessionId,
      'token_type': 'bearer',
      'user_id': _userId,
      'access_expires_at': '2099-01-01T00:00:00Z',
      'refresh_expires_at': '2099-02-01T00:00:00Z',
      'account_deletion_in_progress': false,
    };

Future<JiYiApiClient> _visualApi() async {
  final api = JiYiApiClient(
    baseUrl: 'https://auth-006-visual.invalid/v1',
    httpClient: MockClient((request) async {
      if (request.url.path == '/v1/auth/login') {
        return http.Response(jsonEncode(_token()), 200, headers: _headers);
      }
      if (request.url.path == '/v1/auth/identities') {
        return http.Response(
          jsonEncode({
            'identities': [
              {
                'identity_id': '33333333-3333-4333-8333-333333333333',
                'provider': 'EMAIL_PASSWORD',
                'subject_hint': 'golden@example.test',
                'verified_at': '2026-10-01T00:00:00Z',
                'linked_at': '2026-10-01T00:00:00Z',
              },
              {
                'identity_id': '44444444-4444-4444-8444-444444444444',
                'provider': 'PHONE',
                'subject_hint': '+86138****5678',
                'verified_at': '2026-10-02T00:00:00Z',
                'linked_at': '2026-10-02T00:00:00Z',
              },
              {
                'identity_id': '55555555-5555-4555-8555-555555555555',
                'provider': 'WECHAT',
                'subject_hint': '微信账号已保护',
                'verified_at': null,
                'linked_at': '2026-10-03T00:00:00Z',
              },
            ],
          }),
          200,
          headers: _headers,
        );
      }
      return http.Response('{}', 404, headers: _headers);
    }),
  );
  await api.login(email: 'golden@example.test', password: 'password-123456');
  return api;
}

Future<void> _pumpAccountSecurity(
  WidgetTester tester, {
  required Size size,
  required double textScale,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  final api = await _visualApi();
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      locale: const Locale('zh', 'CN'),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          textScaler: TextScaler.linear(textScale),
        ),
        child: child!,
      ),
      home: RepaintBoundary(
        key: _canvasKey,
        child: AccountSecurityPage(api: api),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('AUTH-006 account security page fits small screen and large text',
      (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await _pumpAccountSecurity(
      tester,
      size: const Size(320, 844),
      textScale: 1.4,
    );
    expect(find.text('账号与安全'), findsOneWidget);
    expect(find.text('绑定新的登录方式'), findsOneWidget);
    expect(find.text('手机号'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('candidate: AUTH-006 Account Security production surface',
      (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await _pumpAccountSecurity(
      tester,
      size: const Size(390, 844),
      textScale: 1.0,
    );
    expect(find.text('账号与安全'), findsOneWidget);
    if (_candidateMode) {
      await expectLater(
        find.byKey(_canvasKey),
        matchesGoldenFile(
          'uiux_v3_candidates/auth-006/account_security_390.png',
        ),
      );
    }
  });

  testWidgets('candidate: AUTH-006 Account Security small screen large text',
      (tester) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await _pumpAccountSecurity(
      tester,
      size: const Size(320, 844),
      textScale: 1.4,
    );
    expect(find.text('账号与安全'), findsOneWidget);
    if (_candidateMode) {
      await expectLater(
        find.byKey(_canvasKey),
        matchesGoldenFile(
          'uiux_v3_candidates/auth-006/account_security_320_large_text.png',
        ),
      );
    }
  });
}
