import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';
import 'package:jiyidashi/sms_otp.dart';

class _FakeSmsGateway implements SmsOtpGateway {
  int requestCalls = 0;
  int verifyCalls = 0;
  int cancelCalls = 0;
  Completer<SmsOtpRequestResult>? pendingRequest;
  Completer<void>? pendingVerify;

  @override
  Future<SmsOtpRequestResult> requestSmsOtp({required String phone}) {
    requestCalls += 1;
    return pendingRequest?.future ?? Future.value(
      SmsOtpRequestResult(
        requestId: 'request-1',
        expiresAt: DateTime.now().toUtc().add(const Duration(minutes: 5)),
        cooldownUntil: DateTime.now().toUtc().add(const Duration(seconds: 30)),
      ),
    );
  }

  @override
  Future<void> verifySmsOtp({required String requestId, required String code}) {
    verifyCalls += 1;
    return pendingVerify?.future ?? Future.value();
  }

  @override
  Future<void> cancel() async {
    cancelCalls += 1;
  }
}

Widget _page(SmsOtpGateway gateway, {VoidCallback? onAuthenticated}) {
  return MaterialApp(
    home: SmsOtpPage(
      gateway: gateway,
      privacyConsentGranted: true,
      onAuthenticated: onAuthenticated ?? () {},
    ),
  );
}

void main() {
  testWidgets('SMS request is single-flight and server cooldown disables retry', (tester) async {
    final gateway = _FakeSmsGateway()..pendingRequest = Completer<SmsOtpRequestResult>();
    await tester.pumpWidget(_page(gateway));
    await tester.enterText(find.byType(TextField).first, '+8613800000000');
    await tester.pump();
    await tester.tap(find.text('获取验证码'));
    await tester.pump();
    expect(gateway.requestCalls, 1);
    expect(find.text('正在发送…'), findsOneWidget);
    await tester.tap(find.text('正在发送…'));
    expect(gateway.requestCalls, 1);
    gateway.pendingRequest!.complete(
      SmsOtpRequestResult(
        requestId: 'request-1',
        expiresAt: DateTime.now().toUtc().add(const Duration(minutes: 5)),
        cooldownUntil: DateTime.now().toUtc().add(const Duration(seconds: 60)),
      ),
    );
    await tester.pump();
    expect(find.text('请稍候'), findsOneWidget);
  });

  testWidgets('late verify success after cancel cannot authenticate', (tester) async {
    final gateway = _FakeSmsGateway()
      ..pendingVerify = Completer<void>();
    var authenticated = 0;
    await tester.pumpWidget(_page(gateway, onAuthenticated: () => authenticated += 1));
    await tester.enterText(find.byType(TextField).first, '+8613800000000');
    await tester.pump();
    await tester.tap(find.text('获取验证码'));
    await tester.pump();
    await tester.pump();
    await tester.enterText(find.byType(TextField).last, '123456');
    await tester.pump();
    await tester.tap(find.text('登录'));
    await tester.pump();
    expect(gateway.verifyCalls, 1);
    await tester.tap(find.byIcon(Icons.close));
    await tester.pump();
    expect(gateway.cancelCalls, 1);
    gateway.pendingVerify!.complete();
    await tester.pump();
    expect(authenticated, 0);
  });

  testWidgets('route disposal invalidates API generation before late verify success',
      (tester) async {
    final verifyStarted = Completer<void>();
    final verifyResponse = Completer<http.Response>();
    final store = MemoryAuthSessionStore()..installationId = 'sms-route-installation';
    final api = JiYiApiClient(
      baseUrl: 'https://auth-v3.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/phone/sms/request')) {
          return http.Response(
            jsonEncode({
              'request_id': 'request-1',
              'expires_at': '2030-01-01T00:05:00Z',
              'cooldown_until': '2030-01-01T00:01:00Z',
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        verifyStarted.complete();
        return verifyResponse.future;
      }),
    );
    var authenticated = 0;

    await tester.pumpWidget(
      _page(api, onAuthenticated: () => authenticated += 1),
    );
    await tester.enterText(find.byType(TextField).first, '+8613800000000');
    await tester.pump();
    await tester.tap(find.text('获取验证码'));
    await tester.pump();
    await tester.pump();
    await tester.enterText(find.byType(TextField).last, '123456');
    await tester.pump();
    await tester.tap(find.text('登录'));
    await tester.pump();
    await verifyStarted.future;

    await tester.pumpWidget(const SizedBox.shrink());
    verifyResponse.complete(
      http.Response(
        jsonEncode({
          'access_token': 'late-access-token',
          'refresh_token': 'late-refresh-token-abcdefghijklmnopqrstuvwxyz',
          'session_id': 'late-session',
          'user_id': 'late-user',
          'access_expires_at': '2030-01-01T00:15:00Z',
        }),
        200,
        headers: {'content-type': 'application/json'},
      ),
    );
    await tester.pump();

    expect(authenticated, 0);
    expect(api.accessToken, isNull);
    expect(api.authenticatedUserId, isNull);
    expect(api.authenticatedSessionId, isNull);
    expect(await store.readSession(), isNull);
  });
}
