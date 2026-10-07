import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/amap_privacy_consent.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';

const _memoryV3GoldenPreview = bool.fromEnvironment('MEMORY_V3_GOLDEN_PREVIEW');
const _memoryV3FixtureFontFamily = 'Memory V3 Noto Sans SC';
const _memoryV3FixtureSize = Size(390, 844);

Future<void> _expectMemoryV3Golden(WidgetTester tester, String fileName) async {
  if (!_memoryV3GoldenPreview) return;
  await expectLater(
    find.byType(Scaffold),
    matchesGoldenFile('goldens/$fileName'),
  );
}

Future<void> _scrollMemoryV3IntoView(WidgetTester tester, Finder finder) async {
  if (finder.evaluate().isEmpty) {
    final scrollable = find.byType(Scrollable).first;
    for (var attempt = 0; attempt < 4 && finder.evaluate().isEmpty; attempt += 1) {
      await tester.drag(scrollable, const Offset(0, -420));
      await tester.pumpAndSettle();
    }
  }
  if (finder.evaluate().isEmpty) return;
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
}

class _MemoryV3Consent implements AmapPrivacyConsentAuthority {
  bool accepted = false;

  @override
  Future<void> accept() async => accepted = true;

  @override
  Future<bool> readAccepted() async => accepted;

  @override
  Future<void> revoke() async => accepted = false;
}

class _MemoryV3ZeroQueue extends OfflineQueueStore {
  @override
  Future<int> countAwaitingDelivery(String ownerUserId) async => 0;

  @override
  Future<void> close() async {}
}

class _MemoryV3Api extends JiYiApiClient {
  _MemoryV3Api({this.response, this.pending, this.error})
      : super(baseUrl: 'https://memory-v3.invalid/v1') {
    accessToken = 'memory-v3-token';
    authenticatedUserId = '11111111-1111-4111-8111-111111111111';
  }

  final Map<String, dynamic>? response;
  final Completer<Map<String, dynamic>>? pending;
  final Object? error;
  int queryCalls = 0;

  @override
  Future<Map<String, dynamic>> queryMemory(String question) async {
    queryCalls += 1;
    if (error != null) throw error!;
    return pending?.future ?? response ?? _noAnswer();
  }

  @override
  Future<Map<String, dynamic>> getProfile() async => <String, dynamic>{
        'elder_mode_enabled': false,
      };

  @override
  Future<Map<String, dynamic>> getPrivacyStatus() async => <String, dynamic>{
        'recording_paused': false,
        'paused_until': null,
      };

  @override
  Future<Map<String, dynamic>> getTodayFootprint() async => <String, dynamic>{
        'timezone': 'Asia/Shanghai',
        'day': '2026-09-28',
        'visits': <Map<String, dynamic>>[],
      };
}

Map<String, dynamic> _noAnswer() => <String, dynamic>{
      'answer': null,
      'can_answer': false,
      'certainty': 'unknown',
      'reason': 'NO_EVIDENCE',
      'intent': 'FIND_EVENT',
      'evidence': <Map<String, dynamic>>[],
      'memory_ids': <String>[],
    };

Map<String, dynamic> _answered() => <String, dynamic>{
      'answer': '这是一条来自真实记录的回答。',
      'can_answer': true,
      'certainty': 'confirmed',
      'reason': null,
      'intent': 'FIND_EVENT',
      'evidence': <Map<String, dynamic>>[
        <String, dynamic>{
          'kind': 'MEMORY',
          'id': 'evidence-1',
          'source_type': 'USER_TEXT',
          'memory_source_id': 'memory-1',
          'occurred_at': '2026-09-28T10:00:00Z',
          'excerpt': '真实用户记录摘录',
          'confidence': 1.0,
        },
      ],
      'memory_ids': <String>['memory-1'],
    };

Map<String, dynamic> _dayFootprint() => <String, dynamic>{
      ..._answered(),
      'intent': 'DATE_FOOTPRINT_QUERY',
      'evidence': <Map<String, dynamic>>[],
      'memory_ids': <String>[],
      'day_footprint': <String, dynamic>{
        'timezone': 'Asia/Shanghai',
        'day': '2026-09-28',
        'visits': <Map<String, dynamic>>[
          <String, dynamic>{
            'id': 'visit-1',
            'place_id': 'place-1',
            'place_name': '真实地点',
            'place_latitude': 39.9042,
            'place_longitude': 116.4074,
            'arrived_at': '2026-09-28T02:00:00Z',
            'left_at': '2026-09-28T03:00:00Z',
            'arrived_at_local': '2026-09-28T10:00:00+08:00',
            'left_at_local': '2026-09-28T11:00:00+08:00',
            'confidence': 0.95,
            'visit_source': 'LOCATION_CLUSTER',
            'visit_finalized': true,
          },
        ],
      },
    };

Future<void> _pumpMemory(
  WidgetTester tester,
  _MemoryV3Api api, {
  bool elderMode = false,
  _MemoryV3Consent? consent,
  double textScale = 1.0,
}) async {
  tester.view.physicalSize = _memoryV3FixtureSize;
  tester.view.devicePixelRatio = 1.0;
  tester.binding.platformDispatcher.localeTestValue = const Locale('zh', 'CN');
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
    tester.binding.platformDispatcher.clearLocaleTestValue();
  });
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: JiYiTheme.light(
        elderMode: elderMode,
        fontFamily: _memoryV3FixtureFontFamily,
      ),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          textScaler: TextScaler.linear(textScale),
        ),
        child: child!,
      ),
      home: Scaffold(
        body: SafeArea(
          child: MemoryQueryPage(
            api: api,
            elderMode: elderMode,
            amapPrivacyConsent: consent,
          ),
        ),
      ),
    ),
  );
  await tester.pump();
}

Future<void> _pumpMemoryProductionShell(
  WidgetTester tester,
  _MemoryV3Api api,
) async {
  tester.view.physicalSize = _memoryV3FixtureSize;
  tester.view.devicePixelRatio = 1.0;
  tester.binding.platformDispatcher.localeTestValue = const Locale('zh', 'CN');
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
    tester.binding.platformDispatcher.clearLocaleTestValue();
  });

  // The fixture exercises the authenticated production shell/navigation while
  // keeping native producers out of a visual-only test.
  api.authenticatedUserId = null;
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: JiYiTheme.light(fontFamily: _memoryV3FixtureFontFamily),
      home: AppShell(
        api: api,
        offlineQueue: _MemoryV3ZeroQueue(),
        onLogout: () {},
      ),
    ),
  );
  await tester.pumpAndSettle();
  await tester.tap(find.text('记忆'));
  await tester.pumpAndSettle();
}

Future<void> _loadMemoryV3Font(String family, String path) async {
  final bytes = await File(path).readAsBytes();
  final loader = FontLoader(family)
    ..addFont(Future<ByteData>.value(ByteData.sublistView(bytes)));
  await loader.load();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    await _loadMemoryV3Font(
      _memoryV3FixtureFontFamily,
      'test/assets/visual/NotoSansSC-Regular.otf',
    );
    await _loadMemoryV3Font('MaterialIcons', 'test/fonts/MaterialIcons-Regular.otf');
  });

  testWidgets('Memory V3 default shell and query surface are truthful', (tester) async {
    final api = _MemoryV3Api();
    await _pumpMemory(tester, api);

    expect(find.text('记忆'), findsOneWidget);
    expect(find.text('想找哪段回忆？'), findsOneWidget);
    expect(find.text('最近记下的'), findsOneWidget);
    expect(find.text('你的记忆会在这里出现'), findsOneWidget);
    expect(find.text('和妈妈的照片'), findsOneWidget);
    expect(api.queryCalls, 0);
    await _expectMemoryV3Golden(tester, 'memory_v3_default.png');
  });

  testWidgets('Memory V3 suggestion populates the real query input', (tester) async {
    await _pumpMemory(tester, _MemoryV3Api());

    await tester.tap(find.text('上周去了哪里'));
    await tester.pump();

    expect(find.text('上周去了哪里'), findsWidgets);
    expect(find.byType(TextField), findsOneWidget);
  });

  testWidgets('Memory V3 production shell candidate', (tester) async {
    await _pumpMemoryProductionShell(tester, _MemoryV3Api());

    for (final label in const ['今天', '记忆', '人生', '家庭', '我的']) {
      expect(
        find.byWidgetPredicate(
          (widget) => widget is Semantics && widget.properties.label == label,
        ),
        findsOneWidget,
      );
    }
    expect(
      find.byWidgetPredicate(
        (widget) =>
            widget is Semantics &&
            widget.properties.label == '记忆' &&
            widget.properties.selected == true,
      ),
      findsOneWidget,
    );
    await _expectMemoryV3Golden(tester, 'memory_v3_shell.png');
  });

  testWidgets('Memory V3 preserves shell and submitted input during loading', (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    final api = _MemoryV3Api(pending: pending);
    await _pumpMemory(tester, api);

    await tester.enterText(find.byKey(const ValueKey('memory-query-input')), '我的记录');
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pump();

    expect(find.text('记忆'), findsOneWidget);
    expect(find.text('查找中…'), findsOneWidget);
    expect(find.text('我的记录'), findsOneWidget);
    expect(api.queryCalls, 1);

    pending.complete(_noAnswer());
    await tester.pumpAndSettle();
  });

  testWidgets('Memory V3 answer and evidence remain server-backed', (tester) async {
    final api = _MemoryV3Api(response: _answered());
    await _pumpMemory(tester, api);
    await tester.enterText(find.byType(TextField), '查找真实记录');
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pumpAndSettle();

    expect(find.text('这是一条来自真实记录的回答。'), findsOneWidget);
    await _expectMemoryV3Golden(tester, 'memory_v3_answer.png');
    final evidenceDisclosure = find.text('查看这次回答的依据');
    await _scrollMemoryV3IntoView(tester, evidenceDisclosure);
    await tester.tap(evidenceDisclosure);
    await tester.pumpAndSettle();
    expect(find.text('真实用户记录摘录'), findsOneWidget);
    expect(find.textContaining('用户编辑'), findsNothing);
  });

  testWidgets('Memory V3 no-answer is explicit and does not guess', (tester) async {
    final api = _MemoryV3Api(response: _noAnswer());
    await _pumpMemory(tester, api);
    await tester.enterText(find.byType(TextField), '没有记录的问题');
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pumpAndSettle();

    expect(find.text('没有足够依据'), findsOneWidget);
    expect(find.text('我没有找到能够支持答案的相关记录。'), findsOneWidget);
  });

  testWidgets('Memory V3 does not render an answer when can_answer is false', (tester) async {
    final response = <String, dynamic>{
      ..._noAnswer(),
      'answer': '不应显示的答案',
    };
    final api = _MemoryV3Api(response: response);
    await _pumpMemory(tester, api);
    await tester.enterText(find.byType(TextField), '不可信的问题');
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pumpAndSettle();

    expect(find.text('不应显示的答案'), findsNothing);
    expect(find.text('没有足够依据'), findsOneWidget);
    expect(find.text('我没有找到能够支持答案的相关记录。'), findsOneWidget);
  });

  testWidgets('Memory V3 no-evidence disclosure never claims a footprint', (tester) async {
    final api = _MemoryV3Api(response: _noAnswer());
    await _pumpMemory(tester, api);
    await tester.enterText(find.byType(TextField), '没有证据的问题');
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pumpAndSettle();
    final evidenceDisclosure = find.text('查看这次回答的依据');
    await _scrollMemoryV3IntoView(tester, evidenceDisclosure);
    await tester.tap(evidenceDisclosure);
    await tester.pumpAndSettle();

    expect(find.text('这次回答依据为服务端已形成的足迹记录。'), findsNothing);
    expect(find.text('没有可展示的参考记录，请谨慎使用这个答案。'), findsOneWidget);
  });

  testWidgets('Memory V3 day footprint stays real and consent-gated', (tester) async {
    final consent = _MemoryV3Consent();
    final api = _MemoryV3Api(response: _dayFootprint());
    await _pumpMemory(tester, api, consent: consent);
    await tester.enterText(find.byType(TextField), '我那天去了哪里');
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pumpAndSettle();

    final place = find.textContaining('真实地点');
    await _scrollMemoryV3IntoView(tester, place);
    expect(place, findsWidgets);
    expect(
      find.byKey(const ValueKey('memory-query-day-map'), skipOffstage: false),
      findsOneWidget,
    );
    expect(
      find.byKey(
        const ValueKey('memory-query-amap-privacy-accept'),
        skipOffstage: false,
      ),
      findsOneWidget,
    );
    expect(consent.accepted, isFalse);
  });

  testWidgets('Memory V3 API error is local and recoverable', (tester) async {
    final api = _MemoryV3Api(error: ApiException(503, '服务暂时不可用'));
    await _pumpMemory(tester, api);
    await tester.enterText(find.byType(TextField), '错误状态');
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await tester.pumpAndSettle();

    expect(find.text('暂时无法查找'), findsOneWidget);
    expect(find.text('服务暂时不可用'), findsOneWidget);
    expect(find.text('记忆'), findsOneWidget);
  });

  testWidgets('Memory V3 elder mode keeps the existing no-guess entry', (tester) async {
    await _pumpMemory(tester, _MemoryV3Api(), elderMode: true, textScale: 1.3);

    expect(find.text('我想找东西'), findsOneWidget);
    expect(find.text('帮我找'), findsOneWidget);
    expect(find.text('最近记下的'), findsNothing);
    expect(tester.getSize(find.byKey(const ValueKey('memory-query-submit'))).height,
        greaterThanOrEqualTo(56));
    expect(tester.takeException(), isNull);
  });
}
