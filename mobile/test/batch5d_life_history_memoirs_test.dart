import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:jiyidashi/v2/life_history_page.dart';
import 'package:jiyidashi/v2/memoirs_page.dart';

import 'v2_test_api.dart';

const _candidateMode = bool.fromEnvironment('UIUX_V3_BATCH5D_CANDIDATE_MODE');
const _batch5dFontFamily = 'Batch 5D Noto Sans SC';

Future<void> _loadBatch5dFonts() async {
  final cjkBytes = await File('test/assets/visual/NotoSansSC-Regular.otf')
      .readAsBytes();
  final cjk = FontLoader(_batch5dFontFamily)
    ..addFont(Future<ByteData>.value(ByteData.sublistView(cjkBytes)));
  await cjk.load();

  final iconBytes = await File('test/fonts/MaterialIcons-Regular.otf')
      .readAsBytes();
  final icons = FontLoader('MaterialIcons')
    ..addFont(Future<ByteData>.value(ByteData.sublistView(iconBytes)));
  await icons.load();
}

class _NoEvidenceApi extends V2TestApi {
  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final uri = Uri.parse(path);
    if (method == 'POST' && uri.path == '/memoirs/annual') {
      return {
        'status': 'MEMOIR_EMPTY',
        'target_year': body?['target_year'] ?? '2025',
        'timezone': 'Asia/Shanghai',
        'narrative_status': 'NO_SUMMARIZABLE_EVIDENCE',
        'narrative': null,
        'narrative_citations': const [],
        'timeline_items': const [],
        'timeline_next_cursor': null,
        'photo_items': const [],
        'photo_next_cursor': null,
      };
    }
    if (method == 'GET' && uri.path == '/memoirs/life/stages') {
      return {'items': const [], 'next_cursor': null};
    }
    return super.requestV2Json(method, path, body: body);
  }
}

class _DelayedHistoryApi extends V2TestApi {
  final Completer<void> release = Completer<void>();
  int historyCalls = 0;

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final uri = Uri.parse(path);
    if (method == 'GET' && uri.path == '/life-history/timeline') {
      historyCalls += 1;
      await release.future;
    }
    return super.requestV2Json(method, path, body: body);
  }
}

class _TimezoneBoundaryApi extends V2TestApi {
  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final uri = Uri.parse(path);
    if (method == 'GET' && uri.path == '/life-history/timeline') {
      return {
        'timezone': 'Asia/Shanghai',
        'start_year': 2024,
        'end_year': 2025,
        'as_of': '2026-09-29T00:00:00Z',
        'items': [
          {
            'kind': 'LIFE_EVENT',
            'occurred_at': '2024-12-31T16:30:00Z',
            'title': '跨年记录',
            'custom_label': null,
            'life_event_id': v2EventId,
            'event_kind': 'WORK',
            'event_ended_at': null,
            'place_id': null,
            'life_stage_id': null,
            'stage_kind': null,
          },
        ],
        'next_cursor': null,
      };
    }
    return super.requestV2Json(method, path, body: body);
  }
}

class _TaggedMemoirApi extends V2TestApi {
  _TaggedMemoirApi(this.tag);

  String tag;

  @override
  Map<String, dynamic> get stage => {
        ...super.stage,
        'title': '$tag 阶段',
      };

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final uri = Uri.parse(path);
    if (method == 'GET' && uri.path == '/memoirs/life/stages') {
      return {
        'items': [stage],
        'next_cursor': null,
      };
    }
    return super.requestV2Json(method, path, body: body);
  }
}

Future<void> _pump(
  WidgetTester tester,
  Widget child, {
  Size size = const Size(390, 844),
  double textScale = 1,
  ThemeMode mode = ThemeMode.light,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: JiYiTheme.light(fontFamily: _batch5dFontFamily),
      darkTheme: JiYiTheme.dark(fontFamily: _batch5dFontFamily),
      themeMode: mode,
      builder: (context, rendered) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          textScaler: TextScaler.linear(textScale),
        ),
        child: rendered!,
      ),
      home: child,
    ),
  );
  await tester.pump();
}

Future<void> _loadAnnual(WidgetTester tester) async {
  await tester.enterText(find.byType(TextField).first, '2025');
  final action = find.text('开始回看', skipOffstage: false);
  await _scrollTo(tester, action);
  await tester.tap(action);
  await tester.pumpAndSettle();
}

Future<void> _scrollTo(WidgetTester tester, Finder target) async {
  final scrollView = find.byType(SingleChildScrollView);
  for (var attempt = 0; attempt < 8; attempt++) {
    if (target.evaluate().isNotEmpty) {
      final targetRect = tester.getRect(target);
      final viewportRect = tester.getRect(scrollView);
      if (targetRect.top >= viewportRect.top &&
          targetRect.bottom <= viewportRect.bottom) {
        return;
      }
    }
    await tester.drag(scrollView, const Offset(0, -320));
    await tester.pumpAndSettle();
  }
}

Finder _yearRange(String value) =>
    find.textContaining(value, skipOffstage: false);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(_loadBatch5dFonts);
  testWidgets('Batch 5D multi-year timeline is truthful and navigable', (tester) async {
    await _pump(tester, LifeHistoryPage(api: V2TestApi()));
    await tester.enterText(find.byType(TextField).first, '2020');
    await tester.enterText(find.byType(TextField).last, '2025');
    await tester.tap(find.byKey(const ValueKey('life-history-submit')));
    await tester.pumpAndSettle();

    final range = _yearRange('2020–2025');
    await _scrollTo(tester, range);
    expect(range, findsOneWidget);
    await _scrollTo(tester, find.text('2025年3月', skipOffstage: false));
    expect(find.text('2025年3月'), findsOneWidget);
    await _scrollTo(tester, find.text('加入新团队', skipOffstage: false));
    expect(find.text('加入新团队'), findsOneWidget);
    expect(find.textContaining('Asia/Shanghai'), findsOneWidget);
    expect(find.textContaining('LIFE_EVENT'), findsNothing);
    expect(find.textContaining('memory_id'), findsNothing);

    await tester.tap(find.text('加入新团队'));
    await tester.pumpAndSettle();
    expect(find.text('相关记录'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byType(LifeHistoryPage), findsOneWidget);
  });

  testWidgets('Batch 5D rejects reversed year ranges before API access', (tester) async {
    await _pump(tester, LifeHistoryPage(api: V2TestApi()));
    await tester.enterText(find.byType(TextField).first, '2026');
    await tester.enterText(find.byType(TextField).last, '2025');
    await tester.tap(find.byKey(const ValueKey('life-history-submit')));
    await tester.pump();
    expect(find.textContaining('开始年份不晚于结束年份'), findsOneWidget);
  });

  testWidgets('Batch 5D groups timeline by server timezone', (tester) async {
    await _pump(tester, LifeHistoryPage(api: _TimezoneBoundaryApi()));
    await tester.enterText(find.byType(TextField).first, '2024');
    await tester.enterText(find.byType(TextField).last, '2025');
    await tester.tap(find.byKey(const ValueKey('life-history-submit')));
    await tester.pumpAndSettle();

    final month = find.byKey(
      const ValueKey('history-group-2025年1月'),
      skipOffstage: false,
    );
    await _scrollTo(tester, month);
    expect(month, findsOneWidget);
    expect(find.text('跨年记录'), findsOneWidget);
  });

  testWidgets('Batch 5D annual review and stage chapter remain evidence-labelled', (tester) async {
    await _pump(tester, MemoirsPage(api: V2TestApi()));
    await _loadAnnual(tester);
    expect(find.text('AI 整理'), findsOneWidget);
    expect(find.textContaining('这一年，你开始了新的产品阶段'), findsOneWidget);
    expect(find.text('参考记录 1'), findsOneWidget);

    final refreshStages = find.text('刷新人生阶段', skipOffstage: false);
    await _scrollTo(tester, refreshStages);
    await tester.tap(refreshStages);
    await tester.pumpAndSettle();
    final stage = find.text('产品创业阶段', skipOffstage: false);
    await _scrollTo(tester, stage);
    await tester.tap(stage);
    await _scrollTo(
      tester,
      find.text('生成这个阶段的故事', skipOffstage: false),
    );
    await tester.tap(find.text('生成这个阶段的故事'));
    await tester.pumpAndSettle();
    expect(find.textContaining('这一阶段以产品开发为主线'), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp('可信状态：AI 整理')), findsNWidgets(2));
  });

  testWidgets('Batch 5D no-evidence state never invents a memoir', (tester) async {
    await _pump(tester, MemoirsPage(api: _NoEvidenceApi()));
    await _loadAnnual(tester);
    expect(find.text('目前没有足够的真实记录来生成年度回顾。'), findsOneWidget);
    expect(find.textContaining('这一年，你开始了新的产品阶段'), findsNothing);
    expect(find.text('AI 整理'), findsNothing);
  });

  testWidgets('Batch 5D remains usable at compact width and large text', (tester) async {
    await _pump(
      tester,
      MemoirsPage(api: V2TestApi()),
      size: const Size(320, 568),
      textScale: 2,
      mode: ThemeMode.dark,
    );
    await _loadAnnual(tester);
    expect(tester.takeException(), isNull);
    expect(find.text('回忆总结'), findsOneWidget);
  });

  testWidgets('Batch 5D stale timeline result is fenced after session rebind', (tester) async {
    final api = _DelayedHistoryApi();
    await _pump(tester, LifeHistoryPage(api: api));
    await tester.tap(find.byKey(const ValueKey('life-history-submit')));
    await tester.pump();
    expect(api.historyCalls, 1);
    final previousSessionVersion = api.sessionVersion;
    await api.logout();
    expect(api.sessionVersion, greaterThan(previousSessionVersion));
    api.accessToken = 'v2-test-token-rebound';
    api.authenticatedUserId = '00000000-0000-4000-8000-000000000002';
    api.release.complete();
    await tester.pumpAndSettle();
    expect(find.text('加入新团队'), findsNothing);
  });

  testWidgets('Batch 5D memoir API rebind clears A and reloads B', (tester) async {
    final apiA = _TaggedMemoirApi('账号 A');
    final apiB = _TaggedMemoirApi('账号 B');
    await _pump(tester, MemoirsPage(api: apiA));
    await tester.pumpAndSettle();
    expect(find.text('账号 A 阶段', skipOffstage: false), findsOneWidget);

    await tester.pumpWidget(
      MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: JiYiTheme.light(fontFamily: _batch5dFontFamily),
        home: MemoirsPage(api: apiB),
      ),
    );
    await tester.pump();
    expect(find.text('账号 A 阶段', skipOffstage: false), findsNothing);
    await tester.pumpAndSettle();
    expect(find.text('账号 B 阶段', skipOffstage: false), findsOneWidget);
  });

  testWidgets('Batch 5D same API session rebind clears displayed stages', (tester) async {
    final api = _TaggedMemoirApi('账号 A');
    await _pump(tester, MemoirsPage(api: api));
    await tester.pumpAndSettle();
    expect(find.text('账号 A 阶段', skipOffstage: false), findsOneWidget);

    api.tag = '账号 B';
    await api.logout();
    api.accessToken = 'rebound-token';
    api.authenticatedUserId = '00000000-0000-4000-8000-000000000002';
    await tester.pump();
    expect(find.text('账号 A 阶段', skipOffstage: false), findsNothing);
    await tester.pumpAndSettle();
    expect(find.text('账号 B 阶段', skipOffstage: false), findsOneWidget);
  });

  testWidgets('candidate: Batch 5D multi-year timeline', (tester) async {
    if (!_candidateMode) return;
    await _pump(tester, LifeHistoryPage(api: V2TestApi()));
    await tester.tap(find.byKey(const ValueKey('life-history-submit')));
    await tester.pumpAndSettle();
    await _scrollTo(tester, _yearRange('2020–2025'));
    await expectLater(
      find.byType(LifeHistoryPage),
      matchesGoldenFile('goldens/life_history_v3_batch5d.png'),
    );
  });

  testWidgets('candidate: Batch 5D annual review with evidence', (tester) async {
    if (!_candidateMode) return;
    await _pump(tester, MemoirsPage(api: V2TestApi()));
    await _loadAnnual(tester);
    await expectLater(
      find.byType(MemoirsPage),
      matchesGoldenFile('goldens/annual_review_v3_batch5d.png'),
    );
  });

  testWidgets('candidate: Batch 5D annual photos and memoir chapter', (tester) async {
    if (!_candidateMode) return;
    await _pump(tester, MemoirsPage(api: V2TestApi()));
    await _loadAnnual(tester);
    final refreshStages = find.text('刷新人生阶段', skipOffstage: false);
    await _scrollTo(tester, refreshStages);
    await tester.tap(refreshStages);
    await tester.pumpAndSettle();
    final stage = find.text('产品创业阶段', skipOffstage: false);
    await _scrollTo(tester, stage);
    await tester.tap(stage);
    await _scrollTo(
      tester,
      find.text('生成这个阶段的故事', skipOffstage: false),
    );
    await tester.tap(find.text('生成这个阶段的故事'));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(MemoirsPage),
      matchesGoldenFile('goldens/memoir_chapter_v3_batch5d.png'),
    );
  });

  testWidgets('candidate: Batch 5D loading and no-evidence state', (tester) async {
    if (!_candidateMode) return;
    await _pump(tester, MemoirsPage(api: _NoEvidenceApi()));
    await _loadAnnual(tester);
    await expectLater(
      find.byType(MemoirsPage),
      matchesGoldenFile('goldens/memoir_no_evidence_v3_batch5d.png'),
    );
  });
}
