import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/native_location_bridge.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/onboarding_flow.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';

// [人工注释][CI-005] Golden 只冻结当前产品渲染结果，不为“好测试”改业务组件；
// 统一窗口、DPR、locale 与主题，Linux CI 是首阶段唯一权威像素基线。
const _goldenSize = Size(390, 844);
const _goldenFontFamily = 'JiYi Golden CJK';

// [人工注释][CI-005] Golden 必须显式加载仓库内固定版本的 CJK 字体；禁止依赖 Runner 系统字体，
// 否则 Ubuntu 镜像变化或 flutter_test 缺字会把中文排版回归伪装成稳定结果。
Future<void> _loadGoldenFont() async {
  final bytes = await File('test/fonts/JiYiGoldenCJK-Regular.ttf')
      .readAsBytes();
  final loader = FontLoader(_goldenFontFamily)
    ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
  await loader.load();
}

// [人工注释][CI-005] Flutter Icons.* 的 IconData 固定使用 `MaterialIcons` family；
// Golden 必须显式注册仓库内的 Flutter 3.47.4 MaterialIcons 字体，否则图标会退化成缺字方框。
Future<void> _loadMaterialIconsFont() async {
  final bytes = await File('test/fonts/MaterialIcons-Regular.otf')
      .readAsBytes();
  final loader = FontLoader('MaterialIcons')
    ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
  await loader.load();
}

// Golden 复用生产 Theme；这里只注入仓库固定 CJK 测试字体，禁止再次复制产品色/布局 token。
ThemeData _goldenTheme() => JiYiTheme.light(fontFamily: _goldenFontFamily);

class _GoldenApi extends JiYiApiClient {
  _GoldenApi({
    this.privacyStatus = const {
      'recording_paused': false,
      'paused_until': null,
    },
    this.privacyError,
  }) : super(baseUrl: 'http://golden.invalid/v1') {
    accessToken = 'golden-token';
    authenticatedUserId = '00000000-0000-4000-8000-000000000001';
  }

  final Map<String, dynamic> privacyStatus;
  final ApiException? privacyError;

  @override
  Future<Map<String, dynamic>> getProfile() async => {
    'id': authenticatedUserId,
    'nickname': '测试用户',
    'email': 'golden@example.com',
    'timezone': 'Asia/Shanghai',
    'locale': 'zh-CN',
  };

  @override
  Future<Map<String, dynamic>> getPrivacyStatus() async {
    final error = privacyError;
    if (error != null) throw error;
    return privacyStatus;
  }
}

class _GoldenLocationBridge implements NativeLocationBridge {
  NativeLocationStatus _status({
    NativeLocationRuntime runtime = NativeLocationRuntime.stopped,
  }) {
    return NativeLocationStatus(
      supported: true,
      platform: 'golden',
      permission: NativeLocationPermission.notDetermined,
      runtime: runtime,
      automaticEnabled: false,
      locationServicesEnabled: true,
      reason: runtime == NativeLocationRuntime.paused
          ? 'paused'
          : 'foreground_permission_required',
    );
  }

  @override
  Future<NativeLocationStatus> status(String ownerUserId) async => _status();

  @override
  Future<NativeLocationStatus> requestForegroundPermission(
    String ownerUserId,
  ) async =>
      _status();

  @override
  Future<NativeLocationStatus> enableAutomaticLocation(
    String ownerUserId,
  ) async =>
      _status();

  @override
  Future<NativeLocationStatus> openBackgroundLocationSettings(
    String ownerUserId,
  ) async =>
      _status();

  @override
  Future<NativeLocationStatus> disableAutomaticLocation(
    String ownerUserId,
  ) async =>
      _status();

  @override
  Future<NativeLocationStatus> start(String ownerUserId) async => _status();

  @override
  Future<NativeLocationStatus> pause(String ownerUserId) async =>
      _status(runtime: NativeLocationRuntime.paused);

  @override
  Future<NativeLocationStatus> stop(String ownerUserId) async => _status();
}

// Golden tests must not depend on an unregistered platform channel. Native platform policy
// is covered separately by Flutter bridge tests, Android JVM tests and iOS RunnerTests.
class _GoldenQueue extends OfflineQueueStore {
  @override
  Future<int> countAwaitingDelivery(String ownerUserId) async => 0;

  @override
  Future<void> close() async {}
}

Future<Key> _pumpSurface(WidgetTester tester, Widget child) async {
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

Future<Key> _pumpShell(WidgetTester tester, {JiYiApiClient? api}) async {
  final resolvedApi = api ?? _GoldenApi();
  return _pumpSurface(
    tester,
    AppShell(
      api: resolvedApi,
      offlineQueue: _GoldenQueue(),
      locationBridge: _GoldenLocationBridge(),
      onLogout: () {},
    ),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    await _loadGoldenFont();
    await _loadMaterialIconsFont();
  });

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

  testWidgets('golden: onboarding intro', (tester) async {
    // [人工注释][S1-026] Golden 直接渲染正式 OnboardingIntroPage；固定字体/窗口仍复用本文件统一基线。
    final key = await _pumpSurface(
      tester,
      Scaffold(
        body: SafeArea(
          child: OnboardingIntroPage(onStart: () {}, onSkip: () {}),
        ),
      ),
    );
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/onboarding_intro.png'),
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

  testWidgets('golden: unified capture media controls', (tester) async {
    final key = await _pumpShell(tester);
    await tester.tap(find.text('记一下'));
    await tester.pumpAndSettle();

    final voiceStart =
        find.byKey(const ValueKey<String>('capture-voice-start'));
    await tester.ensureVisible(voiceStart);
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey<String>('capture-photo-camera')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey<String>('capture-photo-gallery')),
      findsOneWidget,
    );
    expect(voiceStart, findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/capture_media.png'),
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

  testWidgets('golden: profile privacy paused', (tester) async {
    final key = await _pumpShell(
      tester,
      api: _GoldenApi(
        privacyStatus: const {
          'recording_paused': true,
          'paused_until': '2026-09-18T01:30:00+08:00',
        },
      ),
    );
    await tester.tap(find.text('我的'));
    await tester.pumpAndSettle();

    // Stage 2 adds a second, deliberate pause indicator for the native producer:
    // one banner is the authoritative server privacy state, the other proves native
    // location production has also converged to paused.
    expect(find.text('自动采集已暂停'), findsNWidgets(2));
    expect(find.textContaining('2026-09-18T01:30:00+08:00'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '恢复记录'), findsOneWidget);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/profile_privacy_paused.png'),
    );
  });

  testWidgets('privacy error stays unknown and never renders active success', (
    tester,
  ) async {
    final key = await _pumpShell(
      tester,
      api: _GoldenApi(privacyError: ApiException(503, '服务端状态读取失败')),
    );
    await tester.tap(find.text('我的'));
    await tester.pumpAndSettle();

    expect(find.text('无法确认当前隐私状态'), findsOneWidget);
    expect(find.text('服务端状态读取失败'), findsOneWidget);
    expect(find.text('当前没有暂停自动采集'), findsNothing);
    expect(find.text('自动采集已暂停'), findsNothing);
    await expectLater(
      find.byKey(key),
      matchesGoldenFile('goldens/profile_privacy_error.png'),
    );
  });
}
