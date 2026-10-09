import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/navigation/jiyi_navigation.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';

class _NavigationTimelineApi extends JiYiApiClient {
  _NavigationTimelineApi()
      : super(baseUrl: 'https://navigation.invalid/v1');

  @override
  Future<Map<String, dynamic>> getTimelineEvents({
    int limit = 30,
    String? cursor,
    String? day,
  }) async {
    return {'items': <Map<String, dynamic>>[], 'next_cursor': null};
  }
}

void main() {
  test('keeps the authenticated five-tab destination contract', () {
    expect(
      JiYiDestinationCatalog.descriptors.map((descriptor) => descriptor.index),
      [0, 1, 2, 3, 4],
    );
    expect(
      JiYiDestinationCatalog.descriptors.map((descriptor) => descriptor.label),
      ['今天', '记忆', '人生', '家庭', '我的'],
    );
    expect(JiYiDestinationCatalog.fromIndex(0), JiYiDestination.today);
    expect(JiYiDestinationCatalog.fromIndex(1), JiYiDestination.memory);
    expect(JiYiDestinationCatalog.fromIndex(2), JiYiDestination.life);
    expect(JiYiDestinationCatalog.fromIndex(3), JiYiDestination.family);
    expect(JiYiDestinationCatalog.fromIndex(4), JiYiDestination.profile);
  });

  test('page factories preserve destination order and selection mapping', () {
    final pages = JiYiDestinationCatalog.buildPages(
      (destination) => Text(destination.label),
    );

    expect(
      pages.map((page) => (page as Text).data),
      ['今天', '记忆', '人生', '家庭', '我的'],
    );

    for (var selectedIndex = 0; selectedIndex < 5; selectedIndex += 1) {
      final selected = JiYiDestinationCatalog.descriptors
          .where(
            (descriptor) => JiYiDestinationCatalog.isSelected(
              descriptor.destination,
              selectedIndex,
            ),
          )
          .toList();
      expect(selected, hasLength(1));
      expect(selected.single.index, selectedIndex);
    }
  });

  test('shell gates hide bottom navigation during protected flows', () {
    expect(
      JiYiShellPolicy.showBottomNavigation(
        onboardingActive: false,
        accountDeletionActive: false,
      ),
      isTrue,
    );
    expect(
      JiYiShellPolicy.showBottomNavigation(
        onboardingActive: true,
        accountDeletionActive: false,
      ),
      isFalse,
    );
    expect(
      JiYiShellPolicy.showBottomNavigation(
        onboardingActive: false,
        accountDeletionActive: true,
      ),
      isFalse,
    );
  });

  testWidgets('detail route returns to its source after pop', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: ElevatedButton(
              key: const ValueKey('open-detail'),
              onPressed: () {
                JiYiNavigator.pushDetail<void>(
                  context,
                  builder: (_) => const Scaffold(
                    body: Center(child: Text('detail')),
                  ),
                );
              },
              child: const Text('source'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.byKey(const ValueKey('open-detail')));
    await tester.pumpAndSettle();
    expect(find.text('detail'), findsOneWidget);

    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('source'), findsOneWidget);
    expect(find.text('detail'), findsNothing);
  });

  testWidgets('retained V2Home production route returns to its source',
      (tester) async {
    expect(JiYiSecondaryRoutePolicy.retainV2Home, isTrue);

    final api = _NavigationTimelineApi();
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: TimelinePage(api: api),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.text('重要的人和人生故事'));
    await tester.pump();
    expect(find.text('记忆与人生'), findsOneWidget);
    expect(find.text('重要的人'), findsOneWidget);
    expect(find.text('我的人生'), findsOneWidget);

    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('重要的人和人生故事'), findsOneWidget);
    expect(find.text('记忆与人生'), findsNothing);
  });
}
