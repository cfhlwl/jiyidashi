import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:jiyidashi/v2/life_editors.dart';
import 'package:jiyidashi/v2/life_stage_detail_page.dart';
import 'package:jiyidashi/v2/life_stages_page.dart';

import 'v2_test_api.dart';

const bool _candidateMode = bool.fromEnvironment(
  'UIUX_V3_BATCH5C_CANDIDATE_MODE',
  defaultValue: false,
);
const _fixtureFontFamily = 'Batch 5C Noto Sans SC';
const _rootKey = ValueKey<String>('batch5c-visual-root');

Future<void> _loadFixtureFonts() async {
  final cjkBytes = await File(
    'test/assets/visual/NotoSansSC-Regular.otf',
  ).readAsBytes();
  final cjk = FontLoader(_fixtureFontFamily)
    ..addFont(Future<ByteData>.value(ByteData.sublistView(cjkBytes)));
  await cjk.load();
  final iconBytes = await File(
    'test/fonts/MaterialIcons-Regular.otf',
  ).readAsBytes();
  final icons = FontLoader('MaterialIcons')
    ..addFont(Future<ByteData>.value(ByteData.sublistView(iconBytes)));
  await icons.load();
}

class _StageMutationApi extends V2TestApi {
  bool linked = false;
  String stageTitle = '产品创业阶段';
  final List<String> mutationPaths = <String>[];

  @override
  Map<String, dynamic> get stage => {
        ...super.stage,
        'title': stageTitle,
      };

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final route = Uri.parse(path).path;
    if (method == 'GET' &&
        route == '/life-stages/' + v2StageId + '/events') {
      return linked
          ? [
              {
                'link_id': v2LinkId,
                'life_event_id': v2EventId,
                'event_kind': 'WORK',
                'title': '加入新团队',
                'custom_label': null,
                'note': '开始新的产品项目',
                'started_at': '2025-03-01T01:00:00Z',
                'ended_at': null,
                'place_id': v2PlaceId,
                'created_at': '2025-03-01T01:00:00Z',
              },
            ]
          : const [];
    }
    if (method == 'POST' &&
        route ==
            '/life-stages/' +
                v2StageId +
                '/events/' +
                v2EventId) {
      linked = true;
      mutationPaths.add(method + ' ' + route);
      return {
        'link_id': v2LinkId,
        'life_event_id': v2EventId,
        'event_kind': 'WORK',
        'title': '加入新团队',
        'custom_label': null,
        'note': '开始新的产品项目',
        'started_at': '2025-03-01T01:00:00Z',
        'ended_at': null,
        'place_id': v2PlaceId,
        'created_at': '2025-03-01T01:00:00Z',
      };
    }
    if (method == 'DELETE' &&
        route ==
            '/life-stages/' +
                v2StageId +
                '/events/' +
                v2EventId) {
      linked = false;
      mutationPaths.add(method + ' ' + route);
      return {};
    }
    if (method == 'PATCH' && route == '/life-stages/' + v2StageId) {
      stageTitle = body?['title']?.toString() ?? stageTitle;
      mutationPaths.add(method + ' ' + route);
      return stage;
    }
    if (method == 'DELETE' && route == '/life-stages/' + v2StageId) {
      mutationPaths.add(method + ' ' + route);
      return {};
    }
    if (method == 'POST' && route == '/life-stages') {
      stageTitle = body?['title']?.toString() ?? stageTitle;
      mutationPaths.add(method + ' ' + route);
      return stage;
    }
    return super.requestV2Json(method, path, body: body);
  }
}

class _DelayedStageApi extends V2TestApi {
  _DelayedStageApi(this.title);

  final String title;
  final Completer<void> release = Completer<void>();

  @override
  Map<String, dynamic> get stage => {
        ...super.stage,
        'title': title,
      };

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    if (method == 'GET' && Uri.parse(path).path == '/life-stages/' + v2StageId) {
      await release.future;
    }
    return super.requestV2Json(method, path, body: body);
  }
}

Future<void> _pump(
  WidgetTester tester,
  Widget child, {
  Size size = const Size(390, 844),
  double textScale = 1,
  ThemeData? theme,
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
      locale: const Locale('zh', 'CN'),
      theme: theme ?? JiYiTheme.light(fontFamily: _fixtureFontFamily),
      builder: (context, rendered) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          textScaler: TextScaler.linear(textScale),
        ),
        child: rendered!,
      ),
      home: RepaintBoundary(key: _rootKey, child: child),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _candidate(
  WidgetTester tester,
  String filename, {
  Finder? finder,
}) async {
  await expectLater(
    finder ?? find.byKey(_rootKey),
    matchesGoldenFile('goldens/' + filename),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(_loadFixtureFonts);

  testWidgets('Life Stages V3 renders canonical list and no raw enum', (
    tester,
  ) async {
    await _pump(tester, LifeStagesPage(api: V2TestApi()));
    expect(find.text('产品创业阶段'), findsOneWidget);
    expect(find.text('工作'), findsOneWidget);
    expect(find.text('WORK'), findsNothing);
    expect(find.textContaining(v2StageId), findsNothing);
    expect(find.byKey(const ValueKey('life-stage-card-' + v2StageId)), findsOneWidget);
  });

  testWidgets('Life Stages V3 opens detail and keeps linked canonical event', (
    tester,
  ) async {
    await _pump(tester, LifeStagesPage(api: V2TestApi()));
    await tester.tap(find.byKey(const ValueKey('life-stage-card-' + v2StageId)));
    await tester.pumpAndSettle();
    expect(find.text('产品创业阶段'), findsOneWidget);
    expect(find.text('关联的人生经历（1）'), findsOneWidget);
    expect(find.text('加入新团队'), findsOneWidget);
    expect(find.byKey(const ValueKey('life-stage-edit')), findsOneWidget);
    expect(find.byKey(const ValueKey('life-stage-delete')), findsOneWidget);
  });

  testWidgets('Life Stage create, edit, link and unlink use canonical routes', (
    tester,
  ) async {
    final api = _StageMutationApi();
    await _pump(tester, LifeStagesPage(api: api));

    await tester.tap(find.byKey(const ValueKey('life-stages-create')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('life-stage-title')), '新的工作阶段');
    await tester.tap(find.byKey(const ValueKey('life-stage-save')));
    await tester.pumpAndSettle();
    expect(api.mutationPaths, contains('POST /life-stages'));

    await tester.tap(find.byKey(const ValueKey('life-stage-card-' + v2StageId)));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('life-stage-edit')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('life-stage-title')), '更新后的阶段');
    await tester.tap(find.byKey(const ValueKey('life-stage-save')));
    await tester.pumpAndSettle();
    expect(api.mutationPaths, contains('PATCH /life-stages/' + v2StageId));

    await tester.tap(find.byKey(const ValueKey('life-stage-link-event')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('life-stage-link-confirm')));
    await tester.pumpAndSettle();
    expect(
      api.mutationPaths,
      contains('POST /life-stages/' + v2StageId + '/events/' + v2EventId),
    );
    expect(find.text('加入新团队'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('life-stage-unlink-' + v2EventId)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消关联'));
    await tester.pumpAndSettle();
    expect(
      api.mutationPaths,
      contains('DELETE /life-stages/' + v2StageId + '/events/' + v2EventId),
    );
  });

  testWidgets('Life Stage stale response cannot cross API or session binding', (
    tester,
  ) async {
    final oldApi = _DelayedStageApi('账号 A 阶段');
    final current = ValueNotifier<JiYiApiClient>(oldApi);
    addTearDown(current.dispose);
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });
    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('zh', 'CN'),
        theme: JiYiTheme.light(fontFamily: _fixtureFontFamily),
        home: ValueListenableBuilder<JiYiApiClient>(
          valueListenable: current,
          builder: (context, api, _) =>
              LifeStageDetailPage(api: api, stageId: v2StageId),
        ),
      ),
    );
    await tester.pump();
    current.value = V2TestApi();
    await tester.pumpAndSettle();
    expect(find.text('产品创业阶段'), findsOneWidget);
    oldApi.release.complete();
    await tester.pumpAndSettle();
    expect(find.text('账号 A 阶段'), findsNothing);
    expect(find.text('产品创业阶段'), findsOneWidget);
  });

  testWidgets('Life Stage states remain accessible at compact width and dark theme', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    try {
      await _pump(
        tester,
        LifeStageDetailPage(api: V2TestApi(), stageId: v2StageId),
        size: const Size(320, 568),
        textScale: 2,
        theme: JiYiTheme.dark(fontFamily: _fixtureFontFamily),
      );
      expect(find.byKey(const ValueKey('life-stage-identity')), findsOneWidget);
      expect(find.byKey(const ValueKey('life-stage-edit')), findsOneWidget);
      expect(tester.takeException(), isNull);
    } finally {
      semantics.dispose();
    }
  });

  testWidgets('candidate: Batch 5C Life Stages production list', (tester) async {
    if (!_candidateMode) return;
    await _pump(tester, LifeStagesPage(api: V2TestApi()));
    await _candidate(tester, 'life_stages_v3_batch5c.png');
  });

  testWidgets('candidate: Batch 5C Life Stage Detail production page', (
    tester,
  ) async {
    if (!_candidateMode) return;
    await _pump(
      tester,
      LifeStageDetailPage(api: V2TestApi(), stageId: v2StageId),
    );
    await _candidate(tester, 'life_stage_detail_v3_batch5c.png');
  });

  testWidgets('candidate: Batch 5C Life Stage Editor production dialog', (
    tester,
  ) async {
    if (!_candidateMode) return;
    await _pump(
      tester,
      Builder(
        builder: (context) => Center(
          child: FilledButton(
            onPressed: () => showDialog<void>(
              context: context,
              builder: (_) => const LifeStageEditorDialog(),
            ),
            child: const Text('打开编辑器'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('打开编辑器'));
    await tester.pumpAndSettle();
    await _candidate(
      tester,
      'life_stage_editor_v3_batch5c.png',
      finder: find.byType(Overlay),
    );
  });
}
