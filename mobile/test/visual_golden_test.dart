import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/stage1_app.dart';

// [人工注释][CI-005] Golden 只冻结当前产品渲染结果，不为“好测试”改业务组件；
// 统一窗口、DPR、locale 与主题，Linux CI 是首阶段唯一权威像素基线。
const _goldenSize = Size(390, 844);

ThemeData _goldenTheme() => ThemeData(
      useMaterial3: true,
      colorSchemeSeed: const Color(0xFF446A57),
      scaffoldBackgroundColor: const Color(0xFFF7F8F6),
    );

class _GoldenApi extends JiYiApiClient {
  _GoldenApi() : super(baseUrl: 'http://golden.invalid/v1') {
    accessToken = 'golden-token';
    authenticatedUserId = '00000000-0000-4000-8000-000000000001';
  }

  @override
  Future<Map<String, dynamic>> getProfile() async => {
        'id': authenticatedUserId,
        'nickname': '测试用户',
        'email': 'golden@example.com',
        'timezone': 'Asia/Shanghai',
        'locale': 'zh-CN',
      };

  @override
  Future<Map<String, dynamic>> getPrivacyStatus() async => {
        'recording_paused': false,
        'paused_until': null,
      };
}

class _GoldenQueue extends OfflineQueueStore {
  @override
  Future<int> countAwaitingDelivery(String ownerUserId) async => 0;

  @override
  Future<void> close() async {}
}

Future<Key> _pumpSurface(
  WidgetTester tester,
  Widget child,
) async {
  tester.view.physicalSize = _goldenSize;
  tester.view.devicePixelRatio = 1.0;
  tester.binding.platformDispatcher.localeTestValue = const Locale('zh', 'CN');
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
    tester.binding.platformDispatcher.clearLocaleTestValue();
  });

  const key = ValueKey<String>('golden-surface');
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: _goldenTheme(),
      home: RepaintBoundary(key: key, child: child),
    ),
  );
  await tester.pumpAndSettle();
  return key;
}

Future<Key> _pumpShell(WidgetTester tester) async {
  final api = _GoldenApi();
  return _pumpSurface(
    tester,
    AppShell(
      api: api,
      offlineQueue: _GoldenQueue(),
      onLogout: () {},
    ),
  );
}

void main() {
  testWidgets('golden: login', (tester) async {
    // [人工注释][CI-005] 登录页使用真实 AuthPage 静态初始态，禁止网络调用和截图后处理。
    final key = await _pumpSurface(
      tester,
      AuthPage(api: _GoldenApi(), onAuthenticated: () {}),
    );
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/auth_login.png'),
    );
  });

  testWidgets('golden: today home', (tester) async {
    final key = await _pumpShell(tester);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/home_today.png'),
    );
  });

  testWidgets('golden: capture and object location', (tester) async {
    final key = await _pumpShell(tester);
    await tester.tap(find.text('记一下'));
    await tester.pumpAndSettle();
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/capture_object.png'),
    );
  });

  testWidgets('golden: memory query', (tester) async {
    final key = await _pumpShell(tester);
    await tester.tap(find.text('问记忆'));
    await tester.pumpAndSettle();
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/memory_query.png'),
    );
  });

  testWidgets('golden: profile and privacy controls', (tester) async {
    // [人工注释][CI-005] Profile 使用确定性的 fake API 返回固定资料/暂停状态，
    // 只稳定异步输入，不复制或重写产品 UI。
    final key = await _pumpShell(tester);
    await tester.tap(find.text('我的'));
    await tester.pumpAndSettle();
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/profile_privacy.png'),
    );
  });
}
