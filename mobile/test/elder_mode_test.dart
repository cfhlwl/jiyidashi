import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';

const _ownerA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const _ownerB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const _jsonHeaders = {'content-type': 'application/json; charset=utf-8'};

http.Response _loginResponse(String owner) => http.Response(
      jsonEncode({
        'access_token': 'token-$owner',
        'token_type': 'bearer',
        'user_id': owner,
      }),
      200,
      headers: _jsonHeaders,
    );

Map<String, dynamic> _profile(String owner, Object? elder) => {
      'id': owner,
      'nickname': '测试用户',
      'email': 'elder@example.com',
      'timezone': 'Asia/Shanghai',
      'locale': 'zh-CN',
      'elder_mode_enabled': elder,
    };

void main() {
  test('Flutter elder theme keeps normal default and enlarges shared targets', () {
    final normal = JiYiTheme.light();
    final elder = JiYiTheme.light(elderMode: true);

    final normalSize = normal.filledButtonTheme.style?.minimumSize?.resolve(<WidgetState>{});
    final elderSize = elder.filledButtonTheme.style?.minimumSize?.resolve({});
    expect(normalSize?.height, 48);
    expect(elderSize?.height, 56);
    expect(
      elder.textTheme.bodyMedium!.fontSize!,
      greaterThan(normal.textTheme.bodyMedium!.fontSize!),
    );
    expect(
      elder.navigationBarTheme.height,
      greaterThan(normal.navigationBarTheme.height!),
    );
    expect(elder.colorScheme.primary, normal.colorScheme.primary);
  });

  test('malformed elder preference fails closed to normal mode', () async {
    var calls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://elder.invalid/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) return _loginResponse(_ownerA);
        return http.Response(
          jsonEncode(_profile(_ownerA, 'true')),
          200,
          headers: _jsonHeaders,
        );
      }),
    );

    await api.login(email: 'a@example.com', password: 'password-123');
    final profile = await api.getProfile();
    expect(profile['elder_mode_enabled'], isFalse);
  });

  test('elder toggle PATCH sends only explicit self preference', () async {
    var calls = 0;
    Map<String, dynamic>? patchBody;
    final api = JiYiApiClient(
      baseUrl: 'https://elder.invalid/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) return _loginResponse(_ownerA);
        expect(request.method, 'PATCH');
        expect(request.url.path, '/v1/user');
        patchBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode(_profile(_ownerA, true)),
          200,
          headers: _jsonHeaders,
        );
      }),
    );

    await api.login(email: 'a@example.com', password: 'password-123');
    final profile = await api.updateElderMode(true);
    expect(patchBody, {'elder_mode_enabled': true});
    expect(profile['elder_mode_enabled'], isTrue);
  });

  test('stale profile response cannot enable elder mode after account switch', () async {
    var calls = 0;
    final oldProfile = Completer<http.Response>();
    final api = JiYiApiClient(
      baseUrl: 'https://elder.invalid/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        if (calls == 1) return _loginResponse(_ownerA);
        if (calls == 2) return oldProfile.future;
        if (calls == 3) return _loginResponse(_ownerB);
        return http.Response(
          jsonEncode(_profile(_ownerB, false)),
          200,
          headers: _jsonHeaders,
        );
      }),
    );

    await api.login(email: 'a@example.com', password: 'password-123');
    final stale = api.getProfile();
    api.logout();
    await api.login(email: 'b@example.com', password: 'password-123');
    oldProfile.complete(
      http.Response(
        jsonEncode(_profile(_ownerA, true)),
        200,
        headers: _jsonHeaders,
      ),
    );

    await expectLater(stale, throwsA(isA<ProtocolException>()));
    final current = await api.getProfile();
    expect(current['id'], _ownerB);
    expect(current['elder_mode_enabled'], isFalse);
  });

  testWidgets('profile renders explicit self elder toggle without changing privacy controls', (
    tester,
  ) async {
    final api = _WidgetElderApi();
    var changed = false;

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: Scaffold(
          body: ProfilePage(
            api: api,
            onElderModeChanged: (value) => changed = value,
            onLogout: () {},
            onAccountDeleteIntentConfirmed: () async {},
            onAccountDeleted: () async {},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('长辈模式'), findsOneWidget);
    expect(find.textContaining('不改变家庭、位置、记忆或隐私权限'), findsOneWidget);
    expect(find.text('记忆暂停'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('elder-mode-toggle')));
    await tester.pumpAndSettle();
    expect(api.lastElderMutation, isTrue);
    expect(changed, isTrue);
  });
}

class _WidgetElderApi extends JiYiApiClient {
  _WidgetElderApi() : super(baseUrl: 'https://widget-elder.invalid/v1') {
    accessToken = 'widget-token';
    authenticatedUserId = _ownerA;
  }

  bool? lastElderMutation;

  @override
  Future<Map<String, dynamic>> getProfile() async => _profile(_ownerA, false);

  @override
  Future<Map<String, dynamic>> updateElderMode(bool enabled) async {
    lastElderMutation = enabled;
    return _profile(_ownerA, enabled);
  }

  @override
  Future<Map<String, dynamic>> getPrivacyStatus() async => {
        'recording_paused': false,
        'paused_since': null,
        'paused_until': null,
      };
}
