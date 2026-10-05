import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/amap_footprint_map.dart';
import 'package:jiyidashi/footprint_models.dart';

FootprintVisit _visit({
  double? latitude = 39.9042,
  double? longitude = 116.4074,
}) {
  return FootprintVisit.fromJson(<String, dynamic>{
    'id': '11111111-1111-4111-8111-111111111111',
    'place_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'place_name': '测试地点',
    'place_latitude': latitude,
    'place_longitude': longitude,
    'place_address': '测试地址',
    'place_category': 'OFFICE',
    'arrived_at': '2026-10-04T00:00:00Z',
    'left_at': null,
    'arrived_at_local': '2026-10-04T08:00:00+08:00',
    'left_at_local': null,
    'confidence': 1.0,
    'visit_source': 'LOCATION_CLUSTER',
    'visit_finalized': false,
  });
}

void main() {
  testWidgets('privacy denied never constructs native AMap surface', (tester) async {
    var nativeBuilds = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: JiYiFootprintMap(
          visits: <FootprintVisit>[_visit()],
          privacyAccepted: false,
          selectedIndex: 0,
          onSelected: (_) {},
          config: const JiYiAmapConfig(androidKey: 'android-key', platformOverride: TargetPlatform.android),
          nativeBuilder: (context, config, visits, selected, onSelected, interactive) {
            nativeBuilds += 1;
            return const SizedBox();
          },
        ),
      ),
    );

    expect(find.byKey(const ValueKey('amap-privacy-blocked')), findsOneWidget);
    expect(nativeBuilds, 0);
  });

  testWidgets('revoked privacy stops future native AMap construction',
      (tester) async {
    var nativeBuilds = 0;

    Widget surface(bool accepted) => MaterialApp(
          home: JiYiFootprintMap(
            visits: <FootprintVisit>[_visit()],
            privacyAccepted: accepted,
            selectedIndex: 0,
            onSelected: (_) {},
            config: const JiYiAmapConfig(
              androidKey: 'android-key',
              platformOverride: TargetPlatform.android,
            ),
            nativeBuilder:
                (context, config, visits, selected, onSelected, interactive) {
              nativeBuilds += 1;
              return const SizedBox(key: ValueKey('native-amap-test-surface'));
            },
          ),
        );

    await tester.pumpWidget(surface(true));
    expect(find.byKey(const ValueKey('native-amap-test-surface')), findsOneWidget);
    expect(nativeBuilds, 1);

    await tester.pumpWidget(surface(false));
    await tester.pump();
    expect(find.byKey(const ValueKey('amap-privacy-blocked')), findsOneWidget);
    expect(find.byKey(const ValueKey('native-amap-test-surface')), findsNothing);
    expect(nativeBuilds, 1);

    await tester.pumpWidget(surface(false));
    await tester.pump();
    expect(nativeBuilds, 1);
  });

  testWidgets('accepted privacy + SDK key constructs real map adapter', (tester) async {
    var nativeBuilds = 0;
    var receivedCount = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: JiYiFootprintMap(
          visits: <FootprintVisit>[_visit()],
          privacyAccepted: true,
          selectedIndex: 0,
          onSelected: (index) {},
          config: const JiYiAmapConfig(androidKey: 'android-key'),
          nativeBuilder: (context, config, visits, selected, onSelected, interactive) {
            nativeBuilds += 1;
            receivedCount = visits.length;
            return const ColoredBox(color: Colors.white);
          },
        ),
      ),
    );

    expect(find.byKey(const ValueKey('amap-real-surface')), findsOneWidget);
    expect(nativeBuilds, 1);
    expect(receivedCount, 1);
  });

  testWidgets('map marker selection forwards canonical visit index',
      (tester) async {
    int? selectedIndex;

    await tester.pumpWidget(
      MaterialApp(
        home: JiYiFootprintMap(
          visits: <FootprintVisit>[
            _visit(),
            FootprintVisit.fromJson(<String, dynamic>{
              'id': '22222222-2222-4222-8222-222222222222',
              'place_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
              'place_name': '第二地点',
              'place_latitude': 39.9142,
              'place_longitude': 116.4174,
              'place_address': '测试地址 2',
              'place_category': 'OFFICE',
              'arrived_at': '2026-10-04T02:00:00Z',
              'left_at': null,
              'arrived_at_local': '2026-10-04T10:00:00+08:00',
              'left_at_local': null,
              'confidence': 0.97,
              'visit_source': 'LOCATION_CLUSTER',
              'visit_finalized': false,
            }),
          ],
          privacyAccepted: true,
          selectedIndex: 0,
          onSelected: (index) => selectedIndex = index,
          config: const JiYiAmapConfig(
            androidKey: 'android-key',
            platformOverride: TargetPlatform.android,
          ),
          nativeBuilder:
              (context, config, visits, selected, onSelected, interactive) {
            return TextButton(
              key: const ValueKey('fake-amap-marker-1'),
              onPressed: () => onSelected(1),
              child: const Text('第二地点'),
            );
          },
        ),
      ),
    );

    await tester.tap(find.byKey(const ValueKey('fake-amap-marker-1')));
    expect(selectedIndex, 1);
  });

  testWidgets('missing SDK key degrades to factual non-map fallback', (tester) async {
    var nativeBuilds = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: JiYiFootprintMap(
          visits: <FootprintVisit>[_visit()],
          privacyAccepted: true,
          selectedIndex: 0,
          onSelected: (_) {},
          config: const JiYiAmapConfig(
            platformOverride: TargetPlatform.android,
            appEnv: 'development',
          ),
          nativeBuilder: (context, config, visits, selected, onSelected, interactive) {
            nativeBuilds += 1;
            return const SizedBox();
          },
        ),
      ),
    );

    expect(find.byKey(const ValueKey('amap-key-unavailable')), findsOneWidget);
    expect(nativeBuilds, 0);
  });

  testWidgets('production build without platform SDK key fails closed',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: JiYiFootprintMap(
          visits: <FootprintVisit>[_visit()],
          privacyAccepted: true,
          selectedIndex: 0,
          onSelected: (_) {},
          config: const JiYiAmapConfig(
            platformOverride: TargetPlatform.android,
            appEnv: 'production',
          ),
        ),
      ),
    );

    expect(
      tester.takeException(),
      isA<StateError>().having(
        (error) => error.message,
        'message',
        contains('Production AMap configuration'),
      ),
    );
  });

  testWidgets('accepted privacy applies SDK privacy state before initialization',
      (tester) async {
    final calls = <String>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            bootstrapJiYiAmapSdk(
              context,
              const JiYiAmapConfig(
                androidKey: 'android-key',
                platformOverride: TargetPlatform.android,
                appEnv: 'development',
              ),
              hooks: JiYiAmapSdkHooks(
                updatePrivacyAgree: (_) => calls.add('privacy'),
                init: (context, {required apiKey}) => calls.add('init'),
              ),
            );
            return const SizedBox();
          },
        ),
      ),
    );

    expect(calls, <String>['privacy', 'init']);
  });

  testWidgets('missing canonical coordinates never creates fake marker', (tester) async {
    var nativeBuilds = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: JiYiFootprintMap(
          visits: <FootprintVisit>[_visit(latitude: null, longitude: null)],
          privacyAccepted: true,
          selectedIndex: 0,
          onSelected: (_) {},
          config: const JiYiAmapConfig(androidKey: 'android-key'),
          nativeBuilder: (context, config, visits, selected, onSelected, interactive) {
            nativeBuilds += 1;
            return const SizedBox();
          },
        ),
      ),
    );

    expect(find.byKey(const ValueKey('amap-no-coordinate')), findsOneWidget);
    expect(nativeBuilds, 0);
  });
}
