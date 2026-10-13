import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:jiyidashi/v2/life_event_detail_page.dart';
import 'package:jiyidashi/v2/life_events_page.dart';

import 'v2_test_api.dart';

const _ownerB = '00000000-0000-4000-8000-000000000002';
const _eventB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

Map<String, dynamic> _eventPayload({
  required String id,
  required String title,
}) => {
  'id': id,
  'event_kind': 'WORK',
  'title': title,
  'custom_label': null,
  'note': '来自真实事件记录的备注',
  'started_at': '2025-03-01T01:00:00Z',
  'ended_at': null,
  'place_id': v2PlaceId,
  'revision': 2,
  'created_at': '2025-03-01T01:00:00Z',
  'updated_at': '2026-09-20T00:00:00Z',
};

enum _ListMode { records, empty, offline, unauthorized, forbidden, notFound }

class _LifeEventsApi extends V2TestApi {
  _LifeEventsApi({this.listMode = _ListMode.records});

  _ListMode listMode;
  Completer<Object?>? deferredFirstList;
  bool holdFirstList = false;
  bool firstListReleased = false;
  int createCalls = 0;
  int updateCalls = 0;
  int deleteCalls = 0;
  Completer<Object?>? deferredDelete;
  String? lastMutationPath;
  int? mutationFailureStatus;

  Map<String, dynamic> get eventA =>
      _eventPayload(id: v2EventId, title: '加入新团队');

  Map<String, dynamic> get eventB =>
      _eventPayload(id: _eventB, title: '账号 B 的真实经历');

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) {
    final route = Uri.parse(path).path;
    if (method == 'GET' && route == '/life-events') {
      if (holdFirstList && !firstListReleased) {
        deferredFirstList ??= Completer<Object?>();
        return deferredFirstList!.future;
      }
      if (listMode == _ListMode.empty) return Future<Object?>.value(const []);
      if (listMode == _ListMode.offline) {
        return Future<Object?>.error(TransportException('网络连接失败'));
      }
      if (listMode == _ListMode.unauthorized) {
        return Future<Object?>.error(ApiException(401, '401 当前登录已失效'));
      }
      if (listMode == _ListMode.forbidden) {
        return Future<Object?>.error(ApiException(403, '当前账号没有权限查看人生经历'));
      }
      if (listMode == _ListMode.notFound) {
        return Future<Object?>.error(ApiException(404, '人生经历不存在'));
      }
      final rows = authenticatedUserId == _ownerB ? [eventB] : [eventA];
      return Future<Object?>.value(rows);
    }
    if (method == 'GET' && route == '/life-events/$v2EventId') {
      return Future<Object?>.value(eventA);
    }
    if (method == 'GET' && route == '/life-events/$_eventB') {
      return Future<Object?>.value(eventB);
    }
    if (method == 'GET' &&
        route.startsWith('/life-events/') &&
        route.endsWith('/memories')) {
      return Future<Object?>.value([
        {
          'link_id': v2LinkId,
          'memory_id': v2MemoryId,
          'memory_type': 'NOTE',
          'title': '团队记录',
          'content': '2025 年加入了新的产品团队。',
          'occurred_at': '2025-03-01T01:00:00Z',
          'source_type': 'USER_TEXT',
          'created_at': '2025-03-01T01:00:00Z',
        },
      ]);
    }
    if (method == 'POST' && route == '/life-events') {
      createCalls += 1;
      lastMutationPath = path;
      if (mutationFailureStatus != null) {
        return Future<Object?>.error(
          ApiException(mutationFailureStatus!, '保存人生经历失败'),
        );
      }
      final title = body?['title']?.toString() ?? '新建经历';
      return Future<Object?>.value(_eventPayload(id: v2EventId, title: title));
    }
    if (method == 'PATCH' && route.startsWith('/life-events/')) {
      updateCalls += 1;
      lastMutationPath = route;
      if (mutationFailureStatus != null) {
        return Future<Object?>.error(
          ApiException(mutationFailureStatus!, '更新人生经历失败'),
        );
      }
      final id = route.split('/').last;
      return Future<Object?>.value(
        _eventPayload(id: id, title: body?['title']?.toString() ?? '已更新经历'),
      );
    }
    if (method == 'DELETE' && route.startsWith('/life-events/')) {
      deleteCalls += 1;
      lastMutationPath = route;
      if (mutationFailureStatus != null) {
        return Future<Object?>.error(
          ApiException(mutationFailureStatus!, '删除人生经历失败'),
        );
      }
      if (deferredDelete != null) return deferredDelete!.future;
      return Future<Object?>.value(null);
    }
    return super.requestV2Json(method, path, body: body);
  }
}

Future<void> _pumpPage(
  WidgetTester tester,
  Widget child, {
  Size size = const Size(390, 844),
  double textScale = 1.0,
  ThemeData? theme,
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
      theme: theme ?? JiYiTheme.light(),
      locale: const Locale('zh', 'CN'),
      builder: (context, rendered) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(textScale)),
        child: rendered!,
      ),
      home: child,
    ),
  );
  await tester.pump();
}

void main() {
  testWidgets(
    'Batch 5B list uses truthful event data and detail returns to source',
    (tester) async {
      final api = _LifeEventsApi();
      await _pumpPage(tester, LifeEventsPage(api: api));
      await tester.pumpAndSettle();

      expect(find.text('人生经历'), findsWidgets);
      expect(find.text('加入新团队'), findsOneWidget);
      expect(find.textContaining('PERSON'), findsNothing);
      expect(find.textContaining('memory_id'), findsNothing);

      await tester.tap(find.byKey(const ValueKey('life-event-$v2EventId')));
      await tester.pumpAndSettle();
      expect(find.byType(LifeEventDetailPage), findsOneWidget);
      expect(find.textContaining('相关记录'), findsOneWidget);
      expect(find.text('团队记录'), findsOneWidget);

      await tester.tap(find.bySemanticsLabel('返回'));
      await tester.pumpAndSettle();
      expect(find.byType(LifeEventsPage), findsOneWidget);
      expect(find.text('加入新团队'), findsOneWidget);
    },
  );

  testWidgets(
    'Batch 5B create editor validates, saves and uses the real event API',
    (tester) async {
      final api = _LifeEventsApi();
      await _pumpPage(tester, LifeEventsPage(api: api));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('life-event-create')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('life-event-save')));
      await tester.pump();
      expect(find.text('事件标题需为 1–240 个字符'), findsOneWidget);
      expect(api.createCalls, 0);

      await tester.enterText(
        find.byKey(const ValueKey('life-event-title')),
        '我的真实经历',
      );
      await tester.tap(find.byKey(const ValueKey('life-event-save')));
      await tester.pumpAndSettle();
      expect(api.createCalls, 1);
      expect(api.lastMutationPath, '/life-events');
      expect(find.text('已保存：我的真实经历'), findsOneWidget);
    },
  );

  testWidgets(
    'Batch 5B drops stale list response after owner/API binding changes',
    (tester) async {
      final api = _LifeEventsApi()..holdFirstList = true;
      await _pumpPage(tester, LifeEventsPage(api: api));
      await tester.pump();
      expect(find.text('正在读取人生经历'), findsOneWidget);

      api.holdFirstList = false;
      api.authenticatedUserId = _ownerB;
      await tester.pumpWidget(
        MaterialApp(
          theme: JiYiTheme.light(),
          home: LifeEventsPage(api: api),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('账号 B 的真实经历'), findsOneWidget);
      expect(find.text('加入新团队'), findsNothing);

      api.firstListReleased = true;
      api.deferredFirstList!.complete([api.eventA]);
      await tester.pumpAndSettle();
      expect(find.text('账号 B 的真实经历'), findsOneWidget);
      expect(find.text('加入新团队'), findsNothing);
    },
  );

  testWidgets('Batch 5B rebinds after a sessionVersion-only change', (
    tester,
  ) async {
    final api = _LifeEventsApi();
    await _pumpPage(tester, LifeEventsPage(api: api));
    await tester.pumpAndSettle();
    expect(find.text('加入新团队'), findsOneWidget);

    final previousSessionVersion = api.sessionVersion;
    await api.logout();
    api.accessToken = 'v2-rebound-token';
    api.authenticatedUserId = v2OwnerId;
    expect(api.sessionVersion, greaterThan(previousSessionVersion));

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        locale: const Locale('zh', 'CN'),
        home: LifeEventsPage(api: api),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('加入新团队'), findsOneWidget);
    expect(find.text('正在读取人生经历'), findsNothing);
  });

  testWidgets(
    'Batch 5B detail rebinds canonical event id and stale delete cannot pop new detail',
    (tester) async {
      final api = _LifeEventsApi();
      await _pumpPage(
        tester,
        LifeEventDetailPage(api: api, eventId: v2EventId),
      );
      await tester.pumpAndSettle();
      expect(find.text('加入新团队'), findsWidgets);

      api.deferredDelete = Completer<Object?>();
      await tester.tap(find.byKey(const ValueKey('life-event-delete')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('删除').last);
      await tester.pump();
      expect(api.deleteCalls, 1);

      await tester.pumpWidget(
        MaterialApp(
          theme: JiYiTheme.light(),
          home: LifeEventDetailPage(api: api, eventId: _eventB),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('账号 B 的真实经历'), findsWidgets);

      api.deferredDelete!.complete(null);
      await tester.pumpAndSettle();
      expect(find.byType(LifeEventDetailPage), findsOneWidget);
      expect(find.text('账号 B 的真实经历'), findsWidgets);
    },
  );

  testWidgets('Batch 5B keeps explicit empty, offline and blocked states', (
    tester,
  ) async {
    for (final mode in const [
      _ListMode.empty,
      _ListMode.offline,
      _ListMode.unauthorized,
      _ListMode.forbidden,
      _ListMode.notFound,
    ]) {
      await _pumpPage(
        tester,
        LifeEventsPage(api: _LifeEventsApi(listMode: mode)),
      );
      await tester.pumpAndSettle();
      if (mode == _ListMode.empty) {
        expect(find.text('还没有已保存的人生经历'), findsOneWidget);
      } else if (mode == _ListMode.offline) {
        expect(find.bySemanticsLabel(RegExp('当前离线')), findsOneWidget);
      } else if (mode == _ListMode.unauthorized ||
          mode == _ListMode.forbidden) {
        expect(find.bySemanticsLabel(RegExp('暂不可用')), findsOneWidget);
      } else {
        expect(find.bySemanticsLabel(RegExp('暂时无法读取')), findsOneWidget);
      }
    }
  });

  testWidgets(
    'Batch 5B preserves the draft after a conflict mutation failure',
    (tester) async {
      final api = _LifeEventsApi()..mutationFailureStatus = 409;
      await _pumpPage(tester, LifeEventsPage(api: api));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('life-event-create')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('life-event-title')),
        '需要重试的真实经历',
      );
      await tester.tap(find.byKey(const ValueKey('life-event-save')));
      await tester.pumpAndSettle();

      expect(api.createCalls, 1);
      expect(
        find.byKey(const ValueKey('life-event-editor-dialog')),
        findsOneWidget,
      );
      expect(find.text('保存失败，请检查网络后重试。'), findsOneWidget);
      expect(find.text('需要重试的真实经历'), findsOneWidget);
    },
  );

  testWidgets(
    'Batch 5B supports 320 width and 200 percent text without overflow',
    (tester) async {
      final semantics = tester.ensureSemantics();
      try {
        await _pumpPage(
          tester,
          LifeEventsPage(api: _LifeEventsApi()),
          size: const Size(320, 568),
          textScale: 2.0,
        );
        await tester.pumpAndSettle();
        expect(find.text('人生经历'), findsWidgets);
        final card = find.byKey(const ValueKey('life-event-$v2EventId'));
        await tester.ensureVisible(card);
        expect(tester.getSize(card).height, greaterThanOrEqualTo(48));
        expect(
          tester
              .getSemantics(card)
              .getSemanticsData()
              .hasAction(ui.SemanticsAction.tap),
          isTrue,
        );
        expect(tester.takeException(), isNull);
      } finally {
        semantics.dispose();
      }
    },
  );
}
