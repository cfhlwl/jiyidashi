import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:jiyidashi/today_footprint_page.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:jiyidashi/v2/life_page.dart';

import 'v2_test_api.dart';

class _ResponsiveApi extends JiYiApiClient {
  _ResponsiveApi() : super(baseUrl: 'https://responsive.invalid/v1') {
    accessToken = 'responsive-token';
    authenticatedUserId = '00000000-0000-4000-8000-000000000001';
  }

  @override
  Future<Map<String, dynamic>> getTodayFootprint() async => {
        'timezone': 'Asia/Shanghai',
        'day': '2026-09-30',
        'visits': [
          {
            'id': '11111111-1111-4111-8111-111111111111',
            'place_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'place_name': '上海办公室',
            'arrived_at': '2026-09-30T00:10:00Z',
            'left_at': '2026-09-30T02:20:00Z',
            'arrived_at_local': '2026-09-30T08:10:00+08:00',
            'left_at_local': '2026-09-30T10:20:00+08:00',
            'confidence': 0.95,
            'visit_source': 'LOCATION_CLUSTER',
            'visit_finalized': true,
          },
        ],
      };
}

Future<void> _pumpAt(
  WidgetTester tester,
  Widget child, {
  required Size size,
  double textScale = 1.0,
  bool elderMode = false,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });

  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: JiYiTheme.light(elderMode: elderMode),
      builder: (context, rendered) {
        final media = MediaQuery.of(context);
        return MediaQuery(
          data: media.copyWith(textScaler: TextScaler.linear(textScale)),
          child: rendered!,
        );
      },
      home: Scaffold(
        body: SafeArea(child: child),
      ),
    ),
  );
  await tester.pumpAndSettle();
  expect(tester.takeException(), isNull);
}

void main() {
  testWidgets('Product V2 small Android width keeps Today readable', (tester) async {
    await _pumpAt(
      tester,
      TodayPage(api: _ResponsiveApi()),
      size: const Size(320, 640),
    );

    expect(find.text('今天'), findsOneWidget);
    expect(find.text('9月30日 · 星期三'), findsOneWidget);
    expect(find.byKey(const ValueKey('today-footprint-loaded')), findsOneWidget);
    expect(find.textContaining('上海办公室'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Product V2 common phone width keeps Memory primary action usable', (tester) async {
    await _pumpAt(
      tester,
      MemoryQueryPage(api: _ResponsiveApi()),
      size: const Size(390, 844),
    );

    final submit = find.byKey(const ValueKey('memory-query-submit'));
    await tester.ensureVisible(submit);
    await tester.pumpAndSettle();
    expect(tester.getSize(submit).height, greaterThanOrEqualTo(48));
    expect(tester.takeException(), isNull);
  });

  testWidgets('Product V2 large phone keeps Life hierarchy without overflow', (tester) async {
    await _pumpAt(
      tester,
      LifePage(api: V2TestApi()),
      size: const Size(430, 932),
    );

    expect(find.text('我的人生'), findsWidgets);
    expect(find.text('人生经历'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Product V2 text scale 1.3 keeps Memory action visible', (tester) async {
    await _pumpAt(
      tester,
      MemoryQueryPage(api: _ResponsiveApi()),
      size: const Size(390, 844),
      textScale: 1.3,
    );

    final submit = find.byKey(const ValueKey('memory-query-submit'));
    await tester.ensureVisible(submit);
    await tester.pumpAndSettle();
    expect(find.text('想找哪段回忆？'), findsOneWidget);
    expect(tester.getSize(submit).height, greaterThanOrEqualTo(48));
    expect(tester.takeException(), isNull);
  });

  testWidgets('Product V2 Elder keeps 56px action and semantics on small phone', (tester) async {
    final semantics = tester.ensureSemantics();
    await _pumpAt(
      tester,
      MemoryQueryPage(api: _ResponsiveApi(), elderMode: true),
      size: const Size(320, 640),
      textScale: 1.3,
      elderMode: true,
    );

    final submit = find.byKey(const ValueKey('memory-query-submit'));
    await tester.ensureVisible(submit);
    await tester.pumpAndSettle();
    expect(tester.getSize(submit).height, greaterThanOrEqualTo(56));
    final node = tester.getSemantics(submit);
    expect(node.label, contains('帮我找'));
    expect(tester.takeException(), isNull);
    semantics.dispose();
  });
}
