import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/media_presentation_cache.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:jiyidashi/v2/graph_page.dart';
import 'package:jiyidashi/v2/life_event_detail_page.dart';
import 'package:jiyidashi/v2/life_stage_detail_page.dart';
import 'package:jiyidashi/v2/memoirs_page.dart';
import 'package:jiyidashi/v2/people_page.dart';

import 'v2_test_api.dart';

Uint8List _validPngBytes() => base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
    );

Future<void> _pumpUntil(
  WidgetTester tester,
  bool Function() done, {
  int attempts = 30,
}) async {
  for (var index = 0; index < attempts; index++) {
    await tester.pump(const Duration(milliseconds: 50));
    if (done()) return;
  }
  fail('bounded widget pump did not reach expected state');
}

Future<void> pumpSurface(WidgetTester tester, Widget child) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: JiYiTheme.light(),
      home: Scaffold(body: SafeArea(child: child)),
    ),
  );
  await tester.pumpAndSettle();
}

class _MemoirMediaApi extends V2TestApi {
  int capabilityCalls = 0;
  int downloadCalls = 0;

  @override
  Future<MediaDownloadSession> createMediaDownload(String mediaId) async {
    capabilityCalls += 1;
    return MediaDownloadSession(
      mediaId: mediaId,
      cacheVersion:
          'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
      download: SignedDownloadTarget(
        method: 'GET',
        url: Uri.parse('https://storage.invalid/memoir.jpg'),
        headers: const <String, String>{},
        expiresAt: DateTime.utc(2030, 1, 1),
      ),
    );
  }

  @override
  Future<Uint8List> downloadSignedMedia(
    SignedDownloadTarget target, {
    int maxBytes = 50 * 1024 * 1024,
  }) async {
    downloadCalls += 1;
    return _validPngBytes();
  }
}

class OfflineV2TestApi extends V2TestApi {
  OfflineV2TestApi();

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) {
    throw TransportException('网络连接失败');
  }
}

void main() {
  testWidgets('People and Person Detail render canonical V2 data', (tester) async {
    final api = V2TestApi();
    await pumpSurface(tester, PeoplePage(api: api));
    expect(find.text('老张'), findsWidgets);
    expect(find.text('小李'), findsWidgets);
    expect(find.text('最近相关的记忆'), findsOneWidget);

    await tester.tap(find.text('老张').first);
    await tester.pumpAndSettle();
    expect(find.text('认识时长'), findsOneWidget);
    expect(find.textContaining('至少 577 天'), findsOneWidget);
    expect(find.text('关于 TA 的记忆'), findsOneWidget);
    expect(find.text('你们的关系'), findsWidgets);
    expect(find.textContaining('张老师'), findsOneWidget);
  });

  testWidgets('Graph page renders only canonical server neighborhood', (tester) async {
    await pumpSurface(
      tester,
      GraphNeighborhoodPage(
        api: V2TestApi(),
        kind: 'PERSON',
        entityId: v2PersonId,
        title: '老张',
      ),
    );
    expect(find.text('相关的人和事'), findsWidgets);
    expect(find.textContaining('小李'), findsWidgets);
    expect(find.textContaining('你们的关系'), findsOneWidget);
  });

  testWidgets('LifeEvent detail remains deterministic and evidence backed', (tester) async {
    await pumpSurface(
      tester,
      LifeEventDetailPage(api: V2TestApi(), eventId: v2EventId),
    );
    expect(find.text('加入新团队'), findsWidgets);
    expect(find.text('相关记录'), findsOneWidget);
    expect(find.textContaining('团队记录'), findsOneWidget);
    expect(find.text('AI 整理'), findsNothing);
  });

  testWidgets('Long-term Reasoning ANSWERED renders SEC-013 inferred label', (tester) async {
    await pumpSurface(
      tester,
      LifeStageDetailPage(api: V2TestApi(), stageId: v2StageId),
    );
    await tester.enterText(find.byType(TextField).last, '这个阶段发生了什么？');
    final generate = find.text('生成回顾');
    await tester.ensureVisible(generate);
    await tester.pumpAndSettle();
    await tester.tap(generate);
    await tester.pumpAndSettle();
    expect(find.text('AI 整理'), findsOneWidget);
    expect(find.textContaining('持续围绕产品开发'), findsOneWidget);
    expect(find.text('参考记录 1'), findsOneWidget);
  });

  testWidgets('Long-term provider failure never leaks generated prose', (tester) async {
    await pumpSurface(
      tester,
      LifeStageDetailPage(
        api: V2TestApi(reasoningStatus: 'PROVIDER_FAILED'),
        stageId: v2StageId,
      ),
    );
    await tester.enterText(find.byType(TextField).last, '这个阶段发生了什么？');
    final generate = find.text('生成回顾');
    await tester.ensureVisible(generate);
    await tester.pumpAndSettle();
    await tester.tap(generate);
    await tester.pumpAndSettle();
    expect(find.text('暂时无法整理'), findsOneWidget);
    expect(find.textContaining('持续围绕产品开发'), findsNothing);
  });

  testWidgets('Annual Memoir READY labels narrative but not timeline/photos', (tester) async {
    await pumpSurface(tester, MemoirsPage(api: V2TestApi()));
    final yearField = find.byType(TextField).first;
    await tester.enterText(yearField, '2025');
    final annual = find.text('开始回看');
    await tester.ensureVisible(annual);
    await tester.pumpAndSettle();
    await tester.tap(annual);
    await tester.pumpAndSettle();
    expect(find.text('AI 整理'), findsOneWidget);
    expect(find.textContaining('新的产品阶段'), findsOneWidget);
    expect(find.text('这一年的时间线'), findsOneWidget);
    expect(find.text('这一年的照片'), findsOneWidget);
    expect(find.text('团队合影'), findsOneWidget);
  });

  testWidgets('Annual Memoir cached photo preview stays local-first',
      (tester) async {
    final root = await Directory.systemTemp.createTemp('jiyi-memoir-cache-');
    addTearDown(() => root.delete(recursive: true));

    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    await cache.putBytes(
      ownerUserId: v2OwnerId,
      mediaId: v2MediaId,
      cacheVersion:
          'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
      bytes: _validPngBytes(),
    );
    final api = _MemoirMediaApi();

    await pumpSurface(
      tester,
      MemoirsPage(
        api: api,
        mediaCache: cache,
        photoRenderer: (file) => Text('local-memoir-photo:${file.path}'),
      ),
    );
    await tester.enterText(find.byType(TextField).first, '2025');
    final annual = find.text('开始回看');
    await tester.ensureVisible(annual);
    await tester.tap(annual);
    await _pumpUntil(
      tester,
      () => find.text('团队合影').evaluate().isNotEmpty,
    );

    final photo = find.text('团队合影');
    await tester.ensureVisible(photo);
    await tester.tap(photo);
    await _pumpUntil(
      tester,
      () => find.byType(Dialog).evaluate().isNotEmpty &&
          find.textContaining('local-memoir-photo:').evaluate().isNotEmpty,
    );

    expect(find.byType(Dialog), findsOneWidget);
    expect(find.textContaining('local-memoir-photo:'), findsOneWidget);
    expect(api.capabilityCalls, 0);
    expect(api.downloadCalls, 0);

    await tester.tap(find.text('关闭'));
    await _pumpUntil(
      tester,
      () => find.byType(Dialog).evaluate().isEmpty,
    );
    expect(find.byType(Dialog), findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });

  testWidgets('Life Memoir chapter is generated only after explicit stage action', (tester) async {
    await pumpSurface(tester, MemoirsPage(api: V2TestApi()));
    expect(find.textContaining('这一阶段以产品开发为主线'), findsNothing);
    final stage = find.text('产品创业阶段');
    await tester.scrollUntilVisible(
      stage,
      280,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();
    await tester.tap(stage);
    await tester.pumpAndSettle();
    final generate = find.text('生成这个阶段的故事');
    await tester.ensureVisible(generate);
    await tester.tap(generate);
    await tester.pumpAndSettle();
    expect(find.text('AI 整理'), findsOneWidget);
    expect(find.textContaining('这一阶段以产品开发为主线'), findsOneWidget);
  });

  testWidgets('V2 transport failure offers retry instead of offline authority', (tester) async {
    await pumpSurface(tester, PeoplePage(api: OfflineV2TestApi()));
    expect(find.textContaining('网络连接失败'), findsOneWidget);
    expect(find.text('重试'), findsOneWidget);
  });

  testWidgets('V2 trust badge exposes semantics and survives large text', (tester) async {
    final semantics = tester.ensureSemantics();
    try {
      await tester.pumpWidget(
        MaterialApp(
          theme: JiYiTheme.light(),
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context).copyWith(
              textScaler: const TextScaler.linear(1.6),
            ),
            child: child!,
          ),
          home: Scaffold(
            body: SafeArea(
              child: LifeStageDetailPage(
                api: V2TestApi(),
                stageId: v2StageId,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('长期回顾'), findsOneWidget);

      await tester.enterText(
        find.byType(TextField).last,
        '这个阶段发生了什么？',
      );
      final generate = find.text('生成回顾');
      await tester.ensureVisible(generate);
      await tester.pumpAndSettle();
      await tester.tap(generate);
      await tester.pumpAndSettle();

      expect(
        find.bySemanticsLabel(RegExp('可信状态：AI 整理')),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    } finally {
      semantics.dispose();
    }
  });

}
