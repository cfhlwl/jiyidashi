import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/amap_privacy_consent.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/stage1_app.dart';

const _owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

class _MemoryConsentStore implements AmapPrivacyConsentAuthority {
  _MemoryConsentStore(this.accepted);

  bool accepted;

  @override
  Future<void> accept() async => accepted = true;

  @override
  Future<bool> readAccepted() async => accepted;

  @override
  Future<void> revoke() async => accepted = false;
}

class _ProfileApi extends JiYiApiClient {
  _ProfileApi() : super(baseUrl: 'https://profile-map-privacy.invalid/v1') {
    accessToken = 'token';
    authenticatedUserId = _owner;
  }

  @override
  Future<Map<String, dynamic>> getProfile() async => <String, dynamic>{
        'id': _owner,
        'nickname': '测试用户',
        'email': 'test@example.invalid',
        'timezone': 'Asia/Shanghai',
        'elder_mode_enabled': false,
      };

  @override
  Future<Map<String, dynamic>> getPrivacyStatus() async =>
      <String, dynamic>{
        'recording_paused': false,
        'paused_since': null,
        'paused_until': null,
      };
}

void main() {
  testWidgets('AMap consent is persisted only after disclosure confirmation',
      (tester) async {
    final store = _MemoryConsentStore(false);
    var accepted = false;

    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => TextButton(
            onPressed: () async {
              accepted = await requestAmapPrivacyConsent(context, store);
            },
            child: const Text('启用地图'),
          ),
        ),
      ),
    );

    await tester.tap(find.text('启用地图'));
    await tester.pumpAndSettle();

    expect(find.text('启用高德地图服务'), findsOneWidget);
    expect(find.textContaining('高德地图 SDK'), findsOneWidget);
    expect(store.accepted, isFalse);

    await tester.tap(find.byKey(const ValueKey('amap-privacy-confirm')));
    await tester.pumpAndSettle();

    expect(accepted, isTrue);
    expect(store.accepted, isTrue);
  });

  testWidgets('Profile revoke clears shared AMap authority immediately',
      (tester) async {
    final delegate = _MemoryConsentStore(true);
    final controller = AmapPrivacyConsentController(delegate: delegate);
    addTearDown(controller.dispose);
    await controller.readAccepted();

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ProfilePage(
            api: _ProfileApi(),
            amapPrivacyConsent: controller,
            onLogout: () {},
            onAccountDeleteIntentConfirmed: () async {},
            onAccountDeleted: () async {},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final revoke = find.byKey(const ValueKey('amap-privacy-revoke'));
    await tester.ensureVisible(revoke);
    await tester.tap(revoke);
    await tester.pumpAndSettle();

    expect(delegate.accepted, isFalse);
    expect(controller.accepted, isFalse);
    expect(find.byKey(const ValueKey('amap-privacy-enable')), findsOneWidget);
  });
}
