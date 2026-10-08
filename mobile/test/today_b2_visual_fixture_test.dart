import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/amap_footprint_map.dart';
import 'package:jiyidashi/amap_privacy_consent.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/footprint_models.dart';
import 'package:jiyidashi/today_footprint_page.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';

const _fixtureSize = Size(390, 844);
const _fixtureFontFamily = 'B2 Noto Sans SC';
const _fixtureUserId = '00000000-0000-4000-8000-000000000001';
const _leftMediaId = '11111111-1111-4111-8111-111111111111';
const _rightMediaId = '22222222-2222-4222-8222-222222222222';
const _candidateMode = bool.fromEnvironment(
  'UIUX_V3_CANDIDATE_MODE',
  defaultValue: false,
);

class _B2Consent implements AmapPrivacyConsentAuthority {
  @override
  Future<void> accept() async {}

  @override
  Future<bool> readAccepted() async => true;

  @override
  Future<void> revoke() async {}
}

class _B2Api extends JiYiApiClient {
  _B2Api() : super(baseUrl: 'http://today-b2-fixture.invalid/v1') {
    accessToken = 'today-b2-fixture-token';
    authenticatedUserId = _fixtureUserId;
  }

  @override
  Future<Map<String, dynamic>> getTodayFootprint() async => {
        'timezone': 'Asia/Shanghai',
        'day': '2026-10-05',
        'visits': [
          {
            'id': '33333333-3333-4333-8333-333333333333',
            'place_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'place_name': '书房',
            'place_latitude': 31.2304,
            'place_longitude': 121.4737,
            'place_address': '视觉测试书房',
            'place_category': 'HOME',
            'arrived_at': '2026-10-04T23:10:00Z',
            'left_at': '2026-10-05T00:00:00Z',
            'arrived_at_local': '2026-10-05T07:10:00+08:00',
            'left_at_local': '2026-10-05T08:00:00+08:00',
            'confidence': 0.98,
            'visit_source': 'LOCATION_CLUSTER',
            'visit_finalized': true,
          },
          {
            'id': '44444444-4444-4444-8444-444444444444',
            'place_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            'place_name': '公园',
            'place_latitude': 31.2243,
            'place_longitude': 121.4768,
            'place_address': '视觉测试公园',
            'place_category': 'PARK',
            'arrived_at': '2026-10-05T00:35:00Z',
            'left_at': null,
            'arrived_at_local': '2026-10-05T08:35:00+08:00',
            'left_at_local': null,
            'confidence': 0.94,
            'visit_source': 'LOCATION_CLUSTER',
            'visit_finalized': true,
          },
        ],
      };

  @override
  Future<Map<String, dynamic>> getTimelineEvents({
    int limit = 30,
    String? cursor,
    String? day,
  }) async => {
        'timezone': 'Asia/Shanghai',
        'day': day,
        'items': [
          {
            'kind': 'MEMORY',
            'id': '55555555-5555-4555-8555-555555555555',
            'occurred_at': '2026-10-05T01:15:00Z',
            'ended_at': null,
            'place_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'place_name': '书房',
            'memory_type': 'PHOTO',
            'title': '晨光里的白板',
            'content': '早上的阳光照在白板上，把昨晚的想法又看了一遍。',
            'source_type': 'USER_PHOTO',
            'is_confirmed': true,
            'media_id': _leftMediaId,
            'confidence': 1.0,
            'visit_finalized': null,
          },
          {
            'kind': 'MEMORY',
            'id': '66666666-6666-4666-8666-666666666666',
            'occurred_at': '2026-10-05T04:35:00Z',
            'ended_at': null,
            'place_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            'place_name': '公园',
            'memory_type': 'PHOTO',
            'title': '公园拍照',
            'content': '沿着湖边走了一会儿，拍了张喜欢的照片。',
            'source_type': 'USER_PHOTO',
            'is_confirmed': true,
            'media_id': _rightMediaId,
            'confidence': 1.0,
            'visit_finalized': null,
          },
        ],
        'next_cursor': null,
      };

  @override
  Future<Map<String, dynamic>> getPrivacyStatus() async => const {
        'recording_paused': false,
        'paused_until': null,
      };
}

Widget _b2MapRenderer(
  BuildContext context,
  JiYiAmapConfig config,
  List<FootprintVisit> visits,
  int selectedIndex,
  ValueChanged<int> onSelected,
  bool interactive,
) {
  return DecoratedBox(
    key: const ValueKey('today-b2-test-map-renderer'),
    decoration: const BoxDecoration(color: Color(0xFFE7F1F8)),
    child: Stack(
      fit: StackFit.expand,
      children: [
        CustomPaint(
          painter: _B2MapPainter(
            routeColor: const Color(0xFF4F98EE).withValues(alpha: 0.78),
          ),
        ),
        for (var index = 0; index < visits.length; index++)
          Align(
            alignment: Alignment(
              visits.length == 1 ? 0 : -0.65 + (1.3 * index),
              index.isEven ? -0.1 : 0.18,
            ),
            child: GestureDetector(
              onTap: interactive ? () => onSelected(index) : null,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  DecoratedBox(
                    decoration: BoxDecoration(
                      color: index == selectedIndex
                          ? const Color(0xFF2F8AEF)
                          : const Color(0xFF35A992),
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 3),
                    ),
                    child: SizedBox.square(
                      dimension: index == selectedIndex ? 34 : 30,
                      child: Center(
                        child: Icon(
                          index == 0 ? Icons.home_outlined : Icons.forest_outlined,
                          size: 18,
                          color: Colors.white,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 4),
                  DecoratedBox(
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.92),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 3,
                      ),
                      child: Text(
                        visits[index].placeName,
                        style: const TextStyle(
                          color: Color(0xFF1B3556),
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    ),
  );
}

Widget _b2PlaceRenderer(
  BuildContext context,
  JiYiAmapConfig config,
  double latitude,
  double longitude,
  String name,
  String? address,
) {
  return ColoredBox(
    color: const Color(0xFFE7F1F8),
    child: Center(child: Text(name)),
  );
}

ThemeData _b2Theme() {
  return JiYiTheme.light(fontFamily: _fixtureFontFamily);
}

class _B2MapPainter extends CustomPainter {
  const _B2MapPainter({required this.routeColor});

  final Color routeColor;

  @override
  void paint(Canvas canvas, Size size) {
    final road = Paint()
      ..color = Colors.white.withValues(alpha: 0.54)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 8;
    for (var index = 0; index < 4; index++) {
      final path = Path()
        ..moveTo(-20, size.height * (0.2 + index * 0.2))
        ..quadraticBezierTo(
          size.width * 0.42,
          size.height * (0.02 + index * 0.24),
          size.width + 20,
          size.height * (0.18 + index * 0.2),
        );
      canvas.drawPath(path, road);
    }
    final route = Paint()
      ..color = routeColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3;
    final path = Path()
      ..moveTo(size.width * 0.20, size.height * 0.42)
      ..cubicTo(
        size.width * 0.38,
        size.height * 0.10,
        size.width * 0.62,
        size.height * 0.78,
        size.width * 0.82,
        size.height * 0.40,
      );
    canvas.drawPath(path, route);
  }

  @override
  bool shouldRepaint(_B2MapPainter oldDelegate) =>
      oldDelegate.routeColor != routeColor;
}

class _B2BottomNavigation extends StatelessWidget {
  const _B2BottomNavigation();

  static const _items = [
    (Icons.home, '今天'),
    (Icons.photo_library_outlined, '记忆'),
    (Icons.menu_book_outlined, '人生'),
    (Icons.people_outline, '家庭'),
    (Icons.person_outline, '我的'),
  ];

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: const Color(0xFFFFFEFC),
      child: SizedBox(
        height: 70,
        child: Padding(
          padding: const EdgeInsets.only(bottom: 22),
          child: Row(
            children: [
              for (var index = 0; index < _items.length; index++)
                Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        _items[index].$1,
                        size: 23,
                        color: index == 0
                            ? const Color(0xFF2378E8)
                            : const Color(0xFF6D829F),
                      ),
                      const SizedBox(height: 1),
                      Text(
                        _items[index].$2,
                        style: TextStyle(
                          color: index == 0
                              ? const Color(0xFF2378E8)
                              : const Color(0xFF6D829F),
                          fontSize: 12,
                          fontWeight: index == 0
                              ? FontWeight.w700
                              : FontWeight.w500,
                        ),
                      ),
                      const SizedBox(height: 2),
                      if (index == 0)
                        Container(
                          width: 28,
                          height: 3,
                          decoration: BoxDecoration(
                            color: const Color(0xFF2378E8),
                            borderRadius: BorderRadius.circular(999),
                          ),
                        ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

Future<void> _loadB2Font() async {
  final bytes = await File(
    'test/assets/visual/NotoSansSC-Regular.otf',
  ).readAsBytes();
  final loader = FontLoader(_fixtureFontFamily)
    ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
  await loader.load();
}

Future<void> _loadB2MaterialIcons() async {
  final bytes = await File('test/fonts/MaterialIcons-Regular.otf').readAsBytes();
  final loader = FontLoader('MaterialIcons')
    ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
  await loader.load();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    await _loadB2Font();
    await _loadB2MaterialIcons();
  });

  testWidgets('Today B2 deterministic visual fixture', (tester) async {
    tester.view.physicalSize = _fixtureSize;
    tester.view.devicePixelRatio = 1.0;
    tester.binding.platformDispatcher.localeTestValue = const Locale('zh', 'CN');
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
      tester.binding.platformDispatcher.clearLocaleTestValue();
    });

    final left = File('test/assets/visual/today_memory_left.png').readAsBytesSync();
    final right = File('test/assets/visual/today_memory_right.png').readAsBytesSync();
    final leftImage = MemoryImage(left);
    final rightImage = MemoryImage(right);
    final api = _B2Api();
    await tester.pumpWidget(
      MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: _b2Theme(),
          home: JiYiAmapPresentationScope(
            config: const JiYiAmapConfig(
              androidKey: 'today-b2-fixture-key',
              platformOverride: TargetPlatform.android,
              appEnv: 'development',
            ),
            footprintBuilder: _b2MapRenderer,
            placeBuilder: _b2PlaceRenderer,
            child: TodayPage(
              api: api,
              amapPrivacyConsent: _B2Consent(),
              photoThumbnailBuilder: (context, mediaId, fit) => Image(
                image: mediaId == _leftMediaId ? leftImage : rightImage,
                fit: fit,
                gaplessPlayback: true,
              ),
            ),
          ),
          builder: (context, child) => Scaffold(
            body: child,
            bottomNavigationBar: const _B2BottomNavigation(),
          ),
      ),
    );
    await tester.runAsync(() async {
      await precacheImage(leftImage, tester.element(find.byType(MaterialApp)));
      await precacheImage(rightImage, tester.element(find.byType(MaterialApp)));
    });
    for (var frame = 0; frame < 20; frame++) {
      await tester.pump(const Duration(milliseconds: 50));
    }

    expect(find.text('10月5日 · 星期一'), findsOneWidget);
    expect(find.text('说一段'), findsOneWidget);
    expect(find.text('写下来'), findsOneWidget);
    expect(find.text('拍张照'), findsOneWidget);
    expect(find.text('+ 记一下'), findsNothing);
    expect(find.text('晨光里的白板'), findsOneWidget);
    expect(find.text('公园拍照'), findsOneWidget);
    expect(find.byKey(const ValueKey('today-b2-test-map-renderer')), findsOneWidget);
    expect(find.text('今天'), findsNWidgets(2));

    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/design_authority_today.png'),
    );
    if (_candidateMode) {
      await expectLater(
        find.byType(MaterialApp),
        matchesGoldenFile('uiux_v3_candidates/today_v3.png'),
      );
    }
  });
}
