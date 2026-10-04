import 'package:flutter/foundation.dart';
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
  tearDown(() {
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('privacy denied never constructs native AMap surface', (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    var nativeBuilds = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: JiYiFootprintMap(
          visits: <FootprintVisit>[_visit()],
          privacyAccepted: false,
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

    expect(find.byKey(const ValueKey('amap-privacy-blocked')), findsOneWidget);
    expect(nativeBuilds, 0);
  });

  testWidgets('accepted privacy + SDK key constructs real map adapter', (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
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

  testWidgets('missing SDK key degrades to factual non-map fallback', (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    var nativeBuilds = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: JiYiFootprintMap(
          visits: <FootprintVisit>[_visit()],
          privacyAccepted: true,
          selectedIndex: 0,
          onSelected: (_) {},
          config: const JiYiAmapConfig(),
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

  testWidgets('missing canonical coordinates never creates fake marker', (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
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
