import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:jiyidashi/ui/jiyi_v3_components.dart';

void main() {
  testWidgets('V3PageScaffold supports the canonical 390x844 viewport',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: const V3PageScaffold(
          title: '今天',
          child: V3SurfaceCard(
            child: SizedBox(
              width: double.infinity,
              child: Text('390 内容'),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text('今天'), findsOneWidget);
    expect(find.text('390 内容'), findsOneWidget);
  });

  testWidgets('V3PageScaffold and section header reflow on a small viewport',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 568));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: MediaQuery(
          data: const MediaQueryData(
            size: Size(320, 568),
            textScaler: TextScaler.linear(1.4),
          ),
          child: V3PageScaffold(
            title: '记忆',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                V3SectionHeader(
                  title: '需要较长标题的分区',
                  subtitle: '副标题仍然可读',
                  trailing: TextButton(
                    onPressed: () {},
                    child: const Text('查看全部'),
                  ),
                ),
                const SizedBox(height: 16),
                const V3SurfaceCard(
                  child: SizedBox(
                    width: double.infinity,
                    child: Text('卡片内容'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text('记忆'), findsOneWidget);
    expect(find.text('查看全部'), findsOneWidget);
    expect(find.text('卡片内容'), findsOneWidget);
  });

  testWidgets('V3TopBar exposes a reachable back semantic', (tester) async {
    var backPressed = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: V3PageScaffold(
          scrollable: false,
          topBar: V3TopBar(
            title: '详情',
            onBack: () => backPressed += 1,
          ),
          child: const SizedBox.expand(),
        ),
      ),
    );

    final back = find.bySemanticsLabel('返回');
    expect(back, findsOneWidget);
    final backSize = tester.getSize(back);
    expect(backSize.height, greaterThanOrEqualTo(48));
    await tester.tap(back);
    expect(backPressed, 1);
  });

  testWidgets('V3SurfaceCard keeps its interaction semantic and target',
      (tester) async {
    var tapped = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: Scaffold(
          body: V3SurfaceCard(
            semanticLabel: '打开记忆',
            padding: EdgeInsets.zero,
            onTap: () => tapped += 1,
            child: const SizedBox(
              width: double.infinity,
              height: 1,
              child: Text('记忆卡片'),
            ),
          ),
        ),
      ),
    );

    final card = find.bySemanticsLabel('打开记忆');
    expect(card, findsOneWidget);
    final cardSize = tester.getSize(card);
    expect(cardSize.height, greaterThanOrEqualTo(48));
    await tester.tap(card);
    expect(tapped, 1);
  });

  testWidgets('V3StateSurface keeps truthful variants distinct',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: const V3StateSurface(
          variant: V3StateSurfaceVariant.offline,
          title: '当前离线',
          message: '联网后可以重试。',
        ),
      ),
    );

    expect(
      find.bySemanticsLabel('当前离线：当前离线。联网后可以重试。'),
      findsOneWidget,
    );
    expect(find.bySemanticsLabel('加载失败：当前离线。联网后可以重试。'), findsNothing);

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: const V3StateSurface(
          variant: V3StateSurfaceVariant.blocked,
          title: '暂不可用',
          message: '当前操作受到权限限制。',
        ),
      ),
    );

    expect(
      find.bySemanticsLabel('暂不可用：暂不可用。当前操作受到权限限制。'),
      findsOneWidget,
    );
    expect(find.text('当前操作受到权限限制。'), findsOneWidget);

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: const V3StateSurface(
          variant: V3StateSurfaceVariant.loading,
          title: '正在加载',
          message: '请稍候。',
        ),
      ),
    );
    expect(find.bySemanticsLabel('正在加载：正在加载。请稍候。'), findsOneWidget);

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: const V3StateSurface(
          variant: V3StateSurfaceVariant.empty,
          title: '暂无记录',
          message: '没有可展示的内容。',
        ),
      ),
    );
    expect(find.bySemanticsLabel('暂无内容：暂无记录。没有可展示的内容。'), findsOneWidget);
  });

  testWidgets('V3StateSurface actions are explicit and reachable',
      (tester) async {
    var retried = false;

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: V3StateSurface(
          variant: V3StateSurfaceVariant.error,
          title: '加载失败',
          message: '请重试。',
          primaryAction: V3StateAction(
            label: '重试',
            onPressed: () => retried = true,
          ),
        ),
      ),
    );

    await tester.tap(find.text('重试'));
    expect(retried, isTrue);
  });
}
