import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/auth_v3.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:jiyidashi/ui/jiyi_tokens.dart';

const _canvasKey = ValueKey<String>('auth-v3-fixture-canvas');
const _fixtureSize = Size(390, 844);
const _fixtureFontFamily = 'AuthFixtureNotoSansSC';
const _reviewDir = r'D:\jiyi-visual-review\auth-v3-a3';
late ImageProvider<Object> _fixtureHeroImage;

class _AuthV3Fixture extends StatelessWidget {
  const _AuthV3Fixture({required this.screen});

  final AuthV3Screen screen;

  @override
  Widget build(BuildContext context) {
    final capabilities = const AuthCapabilities.allEnabled();
    return RepaintBoundary(
      key: _canvasKey,
      child: Scaffold(
        backgroundColor: JiYiTodayVisuals.background,
        body: Stack(
          children: [
            Positioned(
              top: 0,
              left: 0,
              right: 0,
              child: AuthV3Hero(height: 320, imageProvider: _fixtureHeroImage),
            ),
            SafeArea(
              bottom: false,
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(28, 38, 28, 22),
                child: _screenBody(context, capabilities),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _screenBody(BuildContext context, AuthCapabilities capabilities) {
    return switch (screen) {
      AuthV3Screen.mainLogin => _mainLogin(capabilities),
      AuthV3Screen.phoneOneTap => _providerState(
        icon: Icons.phone_iphone,
        title: '手机号码确认',
        subtitle: '请确认本机号码后，一键进入你的记忆空间。',
        child: Column(
          children: [
            _softSurface('138 **** 8888'),
            const SizedBox(height: 16),
            _primaryButton('一键登录'),
            TextButton(onPressed: () {}, child: const Text('使用其他手机号登录')),
          ],
        ),
      ),
      AuthV3Screen.smsOtp => _providerState(
        icon: Icons.sms_outlined,
        title: '手机号码登录',
        subtitle: '输入手机号，获取验证码。',
        child: Column(
          children: [
            _field('手机号', '+86   请输入手机号'),
            const SizedBox(height: 12),
            _field('验证码', '请输入验证码', trailing: '获取验证码'),
            const SizedBox(height: 16),
            _primaryButton('登录'),
            TextButton(onPressed: () {}, child: const Text('使用邮箱登录')),
          ],
        ),
      ),
      AuthV3Screen.emailLogin => _emailState(),
      AuthV3Screen.oneTapUnavailable => _providerState(
        icon: Icons.phone_disabled_outlined,
        title: '暂时无法获取本机号码',
        subtitle: '可能是当前网络或运营商服务不可用，你可以使用其他方式登录。',
        child: Column(
          children: [
            if (capabilities.smsOtp) _secondaryButton('使用手机验证码登录'),
            if (capabilities.wechat) ...[
              const SizedBox(height: 12),
              _secondaryButton('微信登录'),
            ],
            if (capabilities.email) ...[
              const SizedBox(height: 12),
              _secondaryButton('邮箱登录'),
            ],
          ],
        ),
      ),
    };
  }

  Widget _mainLogin(AuthCapabilities capabilities) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: 15),
        const AuthV3BrandLockup(),
        const SizedBox(height: 162),
        if (capabilities.phoneOneTap)
          const AuthV3PrimaryAction(
            label: '本机号码一键登录',
            icon: Icons.phone_iphone,
            onPressed: _noop,
          ),
        if (capabilities.phoneOneTap) ...[
          const SizedBox(height: 5),
          const Text(
            '快速安全登录，推荐使用',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: JiYiTodayVisuals.secondaryText,
              fontSize: 15,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
        if (capabilities.wechat) ...[
          const SizedBox(height: 31),
          const AuthV3ProviderRow(
            label: '微信登录',
            icon: Icons.chat_bubble_rounded,
            iconColor: Color(0xFF07B65A),
            leading: AuthV3WeChatGlyph(),
            onPressed: _noop,
          ),
        ],
        const SizedBox(height: 48),
        const AuthV3MethodDivider(),
        const SizedBox(height: 20),
        if (capabilities.smsOtp)
          const AuthV3ProviderRow(
            label: '手机号验证码登录',
            icon: Icons.phone_iphone,
            onPressed: _noop,
          ),
        if (capabilities.email) ...[
          const SizedBox(height: 12),
          const AuthV3ProviderRow(
            label: '邮箱登录',
            icon: Icons.mail_outline,
            onPressed: _noop,
          ),
        ],
        const SizedBox(height: 24),
        const AuthV3Agreement(),
      ],
    );
  }

  Widget _emailState() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Transform.translate(
          offset: const Offset(0, -30),
          child: Align(
            alignment: Alignment.centerLeft,
            child: IconButton(
              onPressed: () {},
              icon: const Icon(Icons.chevron_left),
              color: JiYiTodayVisuals.navy,
            ),
          ),
        ),
        const SizedBox(height: 150),
        const Text(
          '邮箱登录',
          style: TextStyle(
            color: JiYiTodayVisuals.navy,
            fontSize: 24,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 8),
        const Text(
          '请输入邮箱和密码',
          style: TextStyle(color: JiYiTodayVisuals.secondaryText, fontSize: 16),
        ),
        const SizedBox(height: 33),
        _field('邮箱地址', '请输入邮箱地址', leading: Icons.mail_outline),
        const SizedBox(height: 14),
        _field(
          '密码',
          '请输入密码',
          leading: Icons.lock_outline,
          trailingIcon: Icons.visibility_off_outlined,
        ),
        const SizedBox(height: 31),
        _primaryButton('登录'),
        TextButton(onPressed: () {}, child: const Text('忘记密码？')),
        const SizedBox(height: 150),
        Container(
          height: 48,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: const Color(0xFFF4F7FB),
            borderRadius: BorderRadius.circular(18),
          ),
          child: TextButton(onPressed: () {}, child: const Text('没有账号？ 去注册')),
        ),
      ],
    );
  }

  Widget _providerState({
    required IconData icon,
    required String title,
    required String subtitle,
    required Widget child,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: IconButton(
            onPressed: () {},
            icon: const Icon(Icons.chevron_left),
            color: JiYiTodayVisuals.navy,
          ),
        ),
        const SizedBox(height: 172),
        Center(
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: const Color(0xFFF4FAFF),
              borderRadius: BorderRadius.circular(999),
            ),
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Icon(icon, size: 44, color: JiYiTodayVisuals.primaryBlue),
            ),
          ),
        ),
        const SizedBox(height: 18),
        Text(
          title,
          textAlign: TextAlign.center,
          style: const TextStyle(
            color: JiYiTodayVisuals.navy,
            fontSize: 24,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          subtitle,
          textAlign: TextAlign.center,
          style: const TextStyle(
            color: JiYiTodayVisuals.secondaryText,
            fontSize: 15,
            height: 1.45,
          ),
        ),
        const SizedBox(height: 20),
        AuthV3Card(child: child),
        const AuthV3Agreement(),
      ],
    );
  }

  Widget _field(
    String label,
    String hint, {
    IconData? leading,
    String? trailing,
    IconData? trailingIcon,
  }) {
    return Container(
      height: 60,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        color: JiYiTodayVisuals.card,
        border: Border.all(color: const Color(0xFFE0E7EF)),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          if (leading != null) ...[
            Icon(leading, size: 22, color: JiYiTodayVisuals.secondaryText),
            const SizedBox(width: 12),
          ],
          Text(
            hint,
            style: const TextStyle(
              color: JiYiTodayVisuals.secondaryText,
              fontSize: 15,
            ),
          ),
          const Spacer(),
          if (trailing != null)
            Text(
              trailing,
              style: const TextStyle(
                color: JiYiTodayVisuals.primaryBlue,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
          if (trailingIcon != null)
            Icon(trailingIcon, size: 20, color: JiYiTodayVisuals.secondaryText),
        ],
      ),
    );
  }

  Widget _softSurface(String text) => Container(
    height: 56,
    alignment: Alignment.center,
    decoration: BoxDecoration(
      color: const Color(0xFFF5F8FC),
      borderRadius: BorderRadius.circular(16),
    ),
    child: Text(
      text,
      style: const TextStyle(
        color: JiYiTodayVisuals.navy,
        fontSize: 18,
        fontWeight: FontWeight.w700,
      ),
    ),
  );

  Widget _primaryButton(String label) => SizedBox(
    height: 56,
    child: FilledButton(
      onPressed: () {},
      style: FilledButton.styleFrom(
        backgroundColor: JiYiTodayVisuals.primaryBlue,
        foregroundColor: Colors.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
      child: Text(label),
    ),
  );

  Widget _secondaryButton(String label) => SizedBox(
    height: 56,
    child: OutlinedButton(
      onPressed: () {},
      style: OutlinedButton.styleFrom(
        backgroundColor: JiYiTodayVisuals.card,
        foregroundColor: JiYiTodayVisuals.navy,
        side: const BorderSide(color: Color(0xFFE0E7EF)),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
      child: Text(label),
    ),
  );
}

void _noop() {}

Future<void> _loadAuthFixtureFont() async {
  final bytes = await File(
    'test/assets/visual/NotoSansSC-Regular.otf',
  ).readAsBytes();
  final loader = FontLoader(_fixtureFontFamily)
    ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
  await loader.load();
  _fixtureHeroImage = MemoryImage(
    await File('assets/brand/today_hero_default.png').readAsBytes(),
  );
}

Future<void> _loadAuthMaterialIcons() async {
  final bytes = await File(
    'test/fonts/MaterialIcons-Regular.otf',
  ).readAsBytes();
  final loader = FontLoader('MaterialIcons')
    ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
  await loader.load();
}

Future<void> _writeFixturePng(WidgetTester tester, String filename) async {
  final boundary = tester.renderObject<RenderRepaintBoundary>(
    find.byKey(_canvasKey),
  );
  final image = await boundary.toImage(pixelRatio: 1.0);
  final data = await image.toByteData(format: ui.ImageByteFormat.png);
  Directory(_reviewDir).createSync(recursive: true);
  File('$_reviewDir/$filename').writeAsBytesSync(data!.buffer.asUint8List());
  image.dispose();
}

Future<void> _pumpAuthFixture(WidgetTester tester, AuthV3Screen screen) async {
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      locale: const Locale('zh', 'CN'),
      theme: JiYiTheme.light(fontFamily: _fixtureFontFamily),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: const TextScaler.linear(1.0)),
        child: child!,
      ),
      home: _AuthV3Fixture(screen: screen),
    ),
  );
  await tester.runAsync(() async {
    await precacheImage(
      _fixtureHeroImage,
      tester.element(find.byType(MaterialApp)),
    );
    await precacheImage(
      const AssetImage('assets/brand/jiyi_logo_primary.png'),
      tester.element(find.byType(MaterialApp)),
    );
  });
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() async {
    await _loadAuthFixtureFont();
    await _loadAuthMaterialIcons();
  });

  Future<void> configureViewport(WidgetTester tester) async {
    tester.view.physicalSize = _fixtureSize;
    tester.view.devicePixelRatio = 1.0;
    tester.binding.platformDispatcher.localeTestValue = const Locale(
      'zh',
      'CN',
    );
  }

  testWidgets('Auth V3 fixture 01 main login', (tester) async {
    await configureViewport(tester);
    await _pumpAuthFixture(tester, AuthV3Screen.mainLogin);
    expect(find.text('本机号码一键登录'), findsOneWidget);
    expect(find.text('邮箱登录'), findsOneWidget);
    if (Platform.environment['JIYI_AUTH_CAPTURE'] == '1') {
      await _writeFixturePng(tester, '01_actual.png');
    }
    await expectLater(
      find.byKey(_canvasKey),
      matchesGoldenFile('goldens/auth_v3_main_login.png'),
    );
  });

  testWidgets('Auth V3 fixture 02 one tap confirmation', (tester) async {
    await configureViewport(tester);
    await _pumpAuthFixture(tester, AuthV3Screen.phoneOneTap);
    expect(find.text('138 **** 8888'), findsOneWidget);
  });

  testWidgets('Auth V3 fixture 03 sms otp', (tester) async {
    await configureViewport(tester);
    await _pumpAuthFixture(tester, AuthV3Screen.smsOtp);
    expect(find.text('获取验证码'), findsOneWidget);
  });

  testWidgets('Auth V3 fixture 04 email', (tester) async {
    await configureViewport(tester);
    await _pumpAuthFixture(tester, AuthV3Screen.emailLogin);
    expect(find.text('邮箱登录'), findsOneWidget);
    if (Platform.environment['JIYI_AUTH_CAPTURE'] == '1') {
      await _writeFixturePng(tester, '04_actual.png');
    }
    await expectLater(
      find.byKey(_canvasKey),
      matchesGoldenFile('goldens/auth_v3_email_login.png'),
    );
  });

  testWidgets('Auth V3 fixture 05 one tap unavailable', (tester) async {
    await configureViewport(tester);
    await _pumpAuthFixture(tester, AuthV3Screen.oneTapUnavailable);
    expect(find.text('暂时无法获取本机号码'), findsOneWidget);
  });
}
