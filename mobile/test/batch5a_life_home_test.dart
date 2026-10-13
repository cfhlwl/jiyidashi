import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/media_presentation_cache.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:jiyidashi/v2/life_events_page.dart';
import 'package:jiyidashi/v2/life_history_page.dart';
import 'package:jiyidashi/v2/life_page.dart';
import 'package:jiyidashi/v2/life_stages_page.dart';
import 'package:jiyidashi/v2/memoirs_page.dart';

import 'v2_test_api.dart';

const _ownerB = '00000000-0000-4000-8000-000000000002';

double _contrastRatio(Color first, Color second) {
  final firstLuminance = first.computeLuminance();
  final secondLuminance = second.computeLuminance();
  final lighter = firstLuminance > secondLuminance
      ? firstLuminance
      : secondLuminance;
  final darker = firstLuminance > secondLuminance
      ? secondLuminance
      : firstLuminance;
  return (lighter + 0.05) / (darker + 0.05);
}

class _LifeApiHost extends StatelessWidget {
  const _LifeApiHost({required this.api});

  final ValueListenable<JiYiApiClient> api;

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<JiYiApiClient>(
      valueListenable: api,
      builder: (_, currentApi, __) => LifePage(api: currentApi),
    );
  }
}

class _TrackingLifeApi extends V2TestApi {
  final List<String> requests = <String>[];

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) {
    requests.add('$method $path');
    return super.requestV2Json(method, path, body: body);
  }
}

Future<void> _pumpLife(
  WidgetTester tester, {
  required JiYiApiClient api,
  LocalMediaCache? mediaCache,
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
      builder: (context, rendered) {
        final media = MediaQuery.of(context);
        return MediaQuery(
          data: media.copyWith(textScaler: TextScaler.linear(textScale)),
          child: rendered!,
        );
      },
      home: LifePage(api: api, mediaCache: mediaCache),
    ),
  );
  await tester.pump();
  expect(tester.takeException(), isNull);
}

void main() {
  testWidgets('Batch 5A renders truthful Life home with four real entries',
      (tester) async {
    final api = _TrackingLifeApi();
    await _pumpLife(tester, api: api);

    expect(find.text('我的人生'), findsOneWidget);
    expect(find.byKey(const ValueKey('life-home-entry-events')), findsOneWidget);
    expect(find.byKey(const ValueKey('life-home-entry-stages')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('life-home-entry-history')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('life-home-entry-memoirs')),
      findsOneWidget,
    );
    expect(find.text('继续整理'), findsOneWidget);
    expect(find.text('打开人生经历，回看并整理自己记录的故事。'), findsOneWidget);
    expect(find.text('查看人生经历'), findsOneWidget);
    expect(find.textContaining('PERSON'), findsNothing);
    expect(find.textContaining('memory_id'), findsNothing);
    expect(api.requests, isEmpty, reason: 'Life home must not prefetch child data');
  });

  testWidgets('Batch 5A routes each entry to the production page and back',
      (tester) async {
    final api = V2TestApi();
    final mediaCache = LocalMediaCache();
    await _pumpLife(tester, api: api, mediaCache: mediaCache);

    Future<void> openAndReturn(Finder entry, Type pageType) async {
      await tester.tap(entry);
      await tester.pumpAndSettle();
      expect(find.byType(pageType), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.byType(LifePage), findsOneWidget);
    }

    await openAndReturn(
      find.byKey(const ValueKey('life-home-entry-events')),
      LifeEventsPage,
    );
    await openAndReturn(
      find.byKey(const ValueKey('life-home-entry-stages')),
      LifeStagesPage,
    );
    await openAndReturn(
      find.byKey(const ValueKey('life-home-entry-history')),
      LifeHistoryPage,
    );

    await tester.tap(find.byKey(const ValueKey('life-home-entry-memoirs')));
    await tester.pumpAndSettle();
    final memoirs = tester.widget<MemoirsPage>(find.byType(MemoirsPage));
    expect(memoirs.api, same(api));
    expect(memoirs.mediaCache, same(mediaCache));
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byType(LifePage), findsOneWidget);
  });

  testWidgets('Batch 5A prevents rapid double navigation and preserves one pop',
      (tester) async {
    final api = V2TestApi();
    await _pumpLife(tester, api: api);
    final entry = find.byKey(const ValueKey('life-home-entry-events'));

    final firstTap = await tester.startGesture(tester.getCenter(entry));
    await firstTap.up();
    final secondTap = await tester.startGesture(tester.getCenter(entry));
    await secondTap.up();
    await tester.pumpAndSettle();

    expect(find.byType(LifeEventsPage), findsOneWidget);
    expect(find.byType(LifePage), findsNothing);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byType(LifePage), findsOneWidget);
  });

  testWidgets('Batch 5A drops a stale owner before route construction',
      (tester) async {
    final api = V2TestApi();
    await _pumpLife(tester, api: api);
    final entry = find.byKey(const ValueKey('life-home-entry-events'));

    final gesture = await tester.startGesture(tester.getCenter(entry));
    await gesture.up();
    api.authenticatedUserId = _ownerB;
    await tester.pumpAndSettle();

    expect(find.byType(LifeEventsPage), findsNothing);
    expect(find.text('会话已变化'), findsOneWidget);
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();

    // Rebind back to the original owner before proving that a fresh route
    // can be opened. The first tap must be dropped; it must not be reused as
    // a valid navigation after the account changes.
    api.authenticatedUserId = v2OwnerId;
    await tester.pumpAndSettle();

    await tester.tap(entry);
    await tester.pumpAndSettle();
    expect(find.byType(LifeEventsPage), findsOneWidget);
    final routePage = tester.widget<LifeEventsPage>(find.byType(LifeEventsPage));
    expect(routePage.api, same(api));
    await tester.pageBack();
    await tester.pumpAndSettle();
  });

  testWidgets('Batch 5A keeps targets and semantics at 320 and 200 percent',
      (tester) async {
    final semantics = tester.ensureSemantics();
    await _pumpLife(
      tester,
      api: V2TestApi(),
      size: const Size(320, 568),
      textScale: 2.0,
    );

    for (final key in const [
      'life-home-entry-events',
      'life-home-entry-stages',
      'life-home-entry-history',
      'life-home-entry-memoirs',
    ]) {
      final finder = find.byKey(ValueKey<String>(key));
      await tester.ensureVisible(finder);
      expect(tester.getSize(finder).height, greaterThanOrEqualTo(48));
      expect(
        tester
            .getSemantics(finder)
            .getSemanticsData()
            .hasAction(ui.SemanticsAction.tap),
        isTrue,
      );
    }
    expect(find.bySemanticsLabel('人生经历'), findsOneWidget);
    expect(tester.takeException(), isNull);
    semantics.dispose();
  });

  testWidgets('Batch 5A supports dark presentation without fake data',
      (tester) async {
    final darkTheme = JiYiTheme.dark();
    await _pumpLife(
      tester,
      api: V2TestApi(),
      size: const Size(390, 844),
      theme: darkTheme,
    );
    expect(find.text('我的人生'), findsOneWidget);
    expect(find.text('人生经历'), findsOneWidget);
    expect(find.text('继续整理'), findsOneWidget);
    expect(find.text('查看人生经历'), findsOneWidget);
    final pageTitle = tester.widget<Text>(find.text('我的人生'));
    final entryTitle = tester.widget<Text>(find.text('人生经历'));
    final continueTitle = tester.widget<Text>(find.text('继续整理'));
    final heroTitle = tester.widget<Text>(find.text('回看、整理、珍藏'));
    expect(
      _contrastRatio(
        pageTitle.style!.color!,
        darkTheme.scaffoldBackgroundColor,
      ),
      greaterThanOrEqualTo(4.5),
    );
    expect(
      _contrastRatio(
        continueTitle.style!.color!,
        darkTheme.colorScheme.surface,
      ),
      greaterThanOrEqualTo(4.5),
    );
    expect(
      _contrastRatio(entryTitle.style!.color!, darkTheme.colorScheme.surface),
      greaterThanOrEqualTo(4.5),
    );
    expect(
      _contrastRatio(heroTitle.style!.color!, darkTheme.colorScheme.surface),
      greaterThanOrEqualTo(4.5),
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('Batch 5A rejects a session-version rebound and accepts a new owner',
      (tester) async {
    final api = V2TestApi();
    await _pumpLife(tester, api: api);
    final entry = find.byKey(const ValueKey('life-home-entry-events'));

    final gesture = await tester.startGesture(tester.getCenter(entry));
    await gesture.up();
    final previousSessionVersion = api.sessionVersion;
    await api.logout();
    expect(api.sessionVersion, greaterThan(previousSessionVersion));
    api.accessToken = 'v2-test-token-b';
    api.authenticatedUserId = _ownerB;
    await tester.pumpAndSettle();

    expect(find.byType(LifeEventsPage), findsNothing);
    expect(find.text('会话已变化'), findsOneWidget);
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();

    await tester.tap(entry);
    await tester.pumpAndSettle();
    final routePage = tester.widget<LifeEventsPage>(find.byType(LifeEventsPage));
    expect(routePage.api, same(api));
    expect(api.authenticatedUserId, _ownerB);
  });

  testWidgets('Batch 5A rejects a queued route after API object rebind',
      (tester) async {
    final apiA = V2TestApi();
    final apiB = V2TestApi()..authenticatedUserId = _ownerB;
    final api = ValueNotifier<JiYiApiClient>(apiA);
    addTearDown(api.dispose);

    await tester.pumpWidget(
      MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: JiYiTheme.light(),
        home: _LifeApiHost(api: api),
      ),
    );
    await tester.pump();
    final entry = find.byKey(const ValueKey('life-home-entry-events'));
    final gesture = await tester.startGesture(tester.getCenter(entry));
    await gesture.up();
    api.value = apiB;
    await tester.pumpAndSettle();

    expect(find.byType(LifeEventsPage), findsNothing);
    expect(find.byType(LifePage), findsOneWidget);
    await tester.tap(entry);
    await tester.pumpAndSettle();
    final routePage = tester.widget<LifeEventsPage>(find.byType(LifeEventsPage));
    expect(routePage.api, same(apiB));
  });
}
