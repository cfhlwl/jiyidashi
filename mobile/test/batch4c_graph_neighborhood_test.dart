import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:jiyidashi/v2/graph_page.dart';
import 'package:jiyidashi/v2/person_detail_page.dart';

import 'v2_test_api.dart';

Map<String, dynamic> _graphPayload({
  required String kind,
  required String centerId,
  required String centerLabel,
  String nodeKind = 'PERSON',
  String nodeId = v2Person2Id,
  String nodeLabel = '小李',
  bool truncated = false,
  bool includeNode = true,
}) {
  final center = {
    'kind': kind,
    'id': centerId,
    'label': centerLabel,
    'occurred_at': null,
  };
  final node = {
    'kind': nodeKind,
    'id': nodeId,
    'label': nodeLabel,
    'occurred_at': null,
  };
  return {
    'center': center,
    'nodes': includeNode ? [node] : const [],
    'edges': includeNode && kind == 'PERSON' && nodeKind == 'PERSON'
        ? [
            {
              'edge_kind': 'PERSON_RELATIONSHIP',
              'source': center,
              'target': node,
              'authority_ref': v2LinkId,
              'metadata': {
                'relationship_kind': 'FRIEND',
                'custom_label': null,
                'relation_kind': null,
                'recorded_at': null,
              },
            },
          ]
        : const [],
    'truncated': truncated,
  };
}

class _GraphFixtureApi extends V2TestApi {
  _GraphFixtureApi({
    this.centerLabel = '老张',
    this.nodeLabel = '小李',
    this.graphGate,
    this.failure,
    this.includeNode = true,
    this.truncated = false,
  }) : super() {
    authenticatedUserId = v2OwnerId;
  }

  final String centerLabel;
  final String nodeLabel;
  final Completer<void>? graphGate;
  final Object? failure;
  final bool includeNode;
  final bool truncated;

  int graphCalls = 0;

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final uri = Uri.parse(path);
    final route = uri.path;
    if (method == 'GET' && route.startsWith('/graph/neighborhood/')) {
      graphCalls += 1;
      final parts = route.split('/');
      final kind = parts[3];
      final centerId = parts[4];
      final gate = graphGate;
      if (gate != null) await gate.future;
      if (failure != null) throw failure!;
      final resolvedCenterLabel = authenticatedUserId == v2OwnerId
          ? (centerId == v2Person2Id ? '小李' : centerLabel)
          : '账号 B 的人物';
      return _graphPayload(
        kind: kind,
        centerId: centerId,
        centerLabel: resolvedCenterLabel,
        nodeId: centerId == v2Person2Id ? v2PersonId : v2Person2Id,
        nodeLabel: nodeLabel,
        includeNode: includeNode,
        truncated: truncated,
      );
    }
    return super.requestV2Json(method, path, body: body);
  }
}

class _EmptyGraphApi extends _GraphFixtureApi {
  _EmptyGraphApi() : super(includeNode: false);
}

Future<void> _pumpGraph(
  WidgetTester tester,
  JiYiApiClient api, {
  String kind = 'PERSON',
  String entityId = v2PersonId,
  String title = '老张',
}) async {
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: JiYiTheme.light(),
      home: GraphNeighborhoodPage(
        api: api,
        kind: kind,
        entityId: entityId,
        title: title,
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('Batch 4C renders only strict server nodes and edge metadata', (
    tester,
  ) async {
    await _pumpGraph(tester, _GraphFixtureApi());

    expect(find.byKey(const ValueKey('graph-center-label')), findsOneWidget);
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('graph-center-label')))
          .data,
      '老张',
    );
    expect(find.text('小李 · 重要的人'), findsOneWidget);
    expect(find.text('朋友'), findsOneWidget);
    expect(find.text('已记录依据 · 人物关系'), findsOneWidget);
    expect(find.textContaining(v2PersonId), findsNothing);
    expect(find.textContaining('PERSON_RELATIONSHIP'), findsNothing);
  });

  testWidgets('Batch 4C keeps empty and truncated graph states truthful', (
    tester,
  ) async {
    await _pumpGraph(tester, _EmptyGraphApi());
    expect(find.byKey(const ValueKey('graph-empty-state')), findsOneWidget);
    expect(find.text('当前内容存在，但服务端没有返回可展示的一跳关系。'), findsOneWidget);
    expect(find.text('没有已记录的关系'), findsOneWidget);

    await _pumpGraph(tester, _GraphFixtureApi(truncated: true));
    expect(
      find.byKey(const ValueKey('graph-truncated-notice')),
      findsOneWidget,
    );
    expect(find.text('仅显示部分直接关联内容。若要继续查看，请从已验证的实体详情重新发起查看。'), findsOneWidget);
  });

  testWidgets('Batch 4C PERSON node opens PersonDetail with canonical id', (
    tester,
  ) async {
    await _pumpGraph(tester, _GraphFixtureApi());
    await tester.tap(find.text('小李 · 重要的人'));
    await tester.pumpAndSettle();

    final detail = tester.widget<PersonDetailPage>(
      find.byType(PersonDetailPage),
    );
    expect(detail.personId, v2Person2Id);
    Navigator.of(tester.element(find.byType(PersonDetailPage))).pop();
    await tester.pumpAndSettle();
    expect(find.text('朋友'), findsOneWidget);
  });

  testWidgets('Batch 4C does not invent routes for non-PERSON nodes', (
    tester,
  ) async {
    await _pumpGraph(
      tester,
      _GraphFixtureApi(),
      kind: 'PLACE',
      entityId: v2PlaceId,
      title: '常去的咖啡店',
    );
    expect(find.text('小李 · 重要的人'), findsOneWidget);
    expect(find.byType(PersonDetailPage), findsNothing);
    await tester.tap(find.text('小李 · 重要的人'));
    await tester.pump();
    expect(find.byType(PersonDetailPage), findsNothing);
  });

  testWidgets('Batch 4C separates offline and forbidden graph states', (
    tester,
  ) async {
    await _pumpGraph(
      tester,
      _GraphFixtureApi(failure: TransportException('offline')),
    );
    expect(find.byKey(const ValueKey('graph-error-state')), findsOneWidget);
    expect(find.text('网络暂时不可用，关联内容尚未读取。'), findsOneWidget);

    await _pumpGraph(
      tester,
      _GraphFixtureApi(failure: ApiException(403, 'FORBIDDEN')),
    );
    expect(find.text('当前账号没有权限查看这些关联内容。'), findsOneWidget);
    expect(find.text('小李 · 重要的人'), findsNothing);
  });

  testWidgets('Batch 4C drops stale graph response after API rebind', (
    tester,
  ) async {
    final release = Completer<void>();
    final oldApi = _GraphFixtureApi(
      graphGate: release,
      centerLabel: '账号 A 的人物',
    );
    await _pumpGraph(tester, oldApi);
    await tester.pump();
    expect(oldApi.graphCalls, 1);

    final newApi = _GraphFixtureApi(
      centerLabel: '账号 B 的人物',
      nodeLabel: '账号 B 的关系',
    );
    await _pumpGraph(tester, newApi);
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('graph-center-label')))
          .data,
      '账号 B 的人物',
    );
    expect(find.text('账号 A 的人物'), findsNothing);

    release.complete();
    await tester.pumpAndSettle();
    expect(find.text('账号 A 的人物'), findsNothing);
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('graph-center-label')))
          .data,
      '账号 B 的人物',
    );
  });

  testWidgets('Batch 4C reloads after same API owner rebind', (tester) async {
    final api = _GraphFixtureApi(centerLabel: '账号 A 的人物');
    await _pumpGraph(tester, api);
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('graph-center-label')))
          .data,
      '账号 A 的人物',
    );

    api.authenticatedUserId = 'owner-b';
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: GraphNeighborhoodPage(
          api: api,
          kind: 'PERSON',
          entityId: v2PersonId,
          title: '旧标题',
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(api.graphCalls, greaterThanOrEqualTo(2));
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('graph-center-label')))
          .data,
      '账号 B 的人物',
    );
    expect(find.text('账号 A 的人物'), findsNothing);
  });

  testWidgets('Batch 4C handles kind and entity rebind without stale center', (
    tester,
  ) async {
    final api = _GraphFixtureApi();
    await _pumpGraph(tester, api);
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('graph-center-label')))
          .data,
      '老张',
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: GraphNeighborhoodPage(
          api: api,
          kind: 'PERSON',
          entityId: v2Person2Id,
          title: '小李',
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('老张'), findsNothing);
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('graph-center-label')))
          .data,
      '小李',
    );
  });

  testWidgets(
    'Batch 4C keeps the newest binding when API changes twice before reload',
    (tester) async {
      final firstApi = _GraphFixtureApi(centerLabel: '账号 A 的人物');
      await _pumpGraph(tester, firstApi);

      final secondApi = _GraphFixtureApi(centerLabel: '账号 B 的人物');
      await tester.pumpWidget(
        MaterialApp(
          theme: JiYiTheme.light(),
          home: GraphNeighborhoodPage(
            api: secondApi,
            kind: 'PERSON',
            entityId: v2PersonId,
            title: '账号 B',
          ),
        ),
      );
      final thirdApi = _GraphFixtureApi(centerLabel: '账号 C 的人物');
      await tester.pumpWidget(
        MaterialApp(
          theme: JiYiTheme.light(),
          home: GraphNeighborhoodPage(
            api: thirdApi,
            kind: 'PERSON',
            entityId: v2Person2Id,
            title: '账号 C',
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(secondApi.graphCalls, lessThanOrEqualTo(1));
      expect(thirdApi.graphCalls, 1);
      expect(
        tester
            .widget<Text>(find.byKey(const ValueKey('graph-center-label')))
            .data,
        '小李',
      );
      expect(find.text('账号 B 的人物'), findsNothing);
      expect(find.text('账号 C 的人物'), findsNothing);
    },
  );

  testWidgets('Batch 4C rejects stale session errors after rebind', (
    tester,
  ) async {
    final release = Completer<void>();
    final api = _GraphFixtureApi(graphGate: release);
    await _pumpGraph(tester, api);
    await tester.pump();

    unawaited(api.logout());
    api.accessToken = 'v2-test-token-b';
    api.authenticatedUserId = 'owner-b';
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: GraphNeighborhoodPage(
          api: api,
          kind: 'PERSON',
          entityId: v2Person2Id,
          title: '新会话',
        ),
      ),
    );
    await tester.pump();
    release.complete();
    await tester.pumpAndSettle();

    expect(find.text('暂时无法读取关联内容，请稍后重试。'), findsNothing);
    expect(find.byKey(const ValueKey('graph-center-label')), findsOneWidget);
  });

  testWidgets('Batch 4C prevents duplicate PERSON navigation', (tester) async {
    await _pumpGraph(tester, _GraphFixtureApi());
    final person = find.text('小李 · 重要的人');
    await tester.tap(person);
    await tester.tap(person, warnIfMissed: false);
    await tester.pumpAndSettle();

    expect(find.byType(PersonDetailPage), findsOneWidget);
    expect(find.byType(GraphNeighborhoodPage), findsNothing);
  });

  testWidgets('Batch 4C route build rechecks graph identity', (tester) async {
    final api = _GraphFixtureApi();
    await _pumpGraph(tester, api);
    await tester.tap(find.text('小李 · 重要的人'));

    // Change the bound session before the route's first frame is built. The
    // route must not construct PersonDetailPage from the old authority.
    api.authenticatedUserId = 'owner-b';
    await tester.pumpAndSettle();

    expect(find.byType(PersonDetailPage), findsNothing);
    expect(find.text('当前关联内容已更新，请返回后重新查看。'), findsOneWidget);
  });

  testWidgets('Batch 4C remains usable at 320 width and 200% text', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 568);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(textScaler: const TextScaler.linear(2)),
          child: child!,
        ),
        home: GraphNeighborhoodPage(
          api: _GraphFixtureApi(
            centerLabel: '一段足够长但必须保持可读的人物名称',
            nodeLabel: '另一段足够长的关系人物名称',
          ),
          kind: 'PERSON',
          entityId: v2PersonId,
          title: '人物关系',
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('朋友'), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp('打开人物详情')), findsOneWidget);
  });
}
