import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/motion_sampling_policy.dart';
import 'package:jiyidashi/native_location_bridge.dart';
import 'package:jiyidashi/native_motion_sampling_bridge.dart';
import 'package:jiyidashi/navigation/jiyi_navigation.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/onboarding_state.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';

const _shellOwner = 'navigation-shell-owner';

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

class _NavigationShellApi extends JiYiApiClient {
  _NavigationShellApi({bool authenticated = false})
      : super(baseUrl: 'https://navigation-shell.invalid/v1') {
    if (authenticated) {
      accessToken = 'navigation-shell-token';
      authenticatedUserId = _shellOwner;
    }
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
        'day': '2026-10-09',
        'visits': <Map<String, dynamic>>[],
      };
}

class _NavigationZeroQueue extends OfflineQueueStore {
  @override
  Future<int> countAwaitingDelivery(String ownerUserId) async => 0;

  @override
  Future<void> close() async {}
}

class _NavigationOnboardingStore implements OnboardingStateStore {
  @override
  Future<OnboardingStatus?> read(String ownerUserId) async => null;

  @override
  Future<void> markInProgress(String ownerUserId) async {}

  @override
  Future<void> markSkipped(String ownerUserId) async {}

  @override
  Future<void> markCompleted(String ownerUserId) async {}

  @override
  Future<void> deleteOwnerState(String ownerUserId) async {}

  @override
  Future<void> close() async {}
}

class _NavigationUnavailableLocation implements NativeLocationBridge {
  static const _status = NativeLocationStatus.unavailable(
    reason: 'navigation-test',
  );

  @override
  Future<NativeLocationStatus> status(String ownerUserId) async => _status;

  @override
  Future<NativeLocationStatus> requestForegroundPermission(
    String ownerUserId,
  ) async =>
      _status;

  @override
  Future<NativeLocationStatus> enableAutomaticLocation(
    String ownerUserId,
  ) async =>
      _status;

  @override
  Future<NativeLocationStatus> openBackgroundLocationSettings(
    String ownerUserId,
  ) async =>
      _status;

  @override
  Future<NativeLocationStatus> openLocationServicesSettings(
    String ownerUserId,
  ) async =>
      _status;

  @override
  Future<NativeLocationStatus> disableAutomaticLocation(
    String ownerUserId,
  ) async =>
      _status;

  @override
  Future<NativeLocationStatus> start(String ownerUserId) async => _status;

  @override
  Future<NativeLocationStatus> pause(String ownerUserId) async => _status;

  @override
  Future<NativeLocationStatus> stop(String ownerUserId) async => _status;
}

class _NavigationNoOpMotion implements NativeMotionSamplingBridge {
  @override
  Stream<void> get samplesAvailable => const Stream<void>.empty();

  @override
  Future<List<NativeLocationSample>> drainSamples(
    String ownerUserId, {
    int limit = 100,
  }) async =>
      const <NativeLocationSample>[];

  @override
  Future<NativeMotionObservation?> takeObservation(String ownerUserId) async =>
      null;

  @override
  Future<void> acknowledgeSamples(
    String ownerUserId,
    List<String> clientUuids,
  ) async {}

  @override
  Future<void> applyProfile(
    String ownerUserId,
    AdaptiveSamplingProfile profile,
  ) async {}

  @override
  Future<LocationProducerMetrics> metrics(String ownerUserId) async =>
      const LocationProducerMetrics(
        wakeups: 0,
        samplesAccepted: 0,
        samplesDropped: 0,
        uploadBatches: 0,
        uploadedSamples: 0,
        activeTrackingDuration: Duration.zero,
      );

  @override
  Future<void> recordUploadBatch(
    String ownerUserId, {
    required int sampleCount,
  }) async {}

  @override
  Future<void> purgeOwner(String ownerUserId) async {}

  @override
  Future<void> close() async {}
}

Future<void> _pumpNormalShell(WidgetTester tester) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: JiYiTheme.light(),
      home: AppShell(
        api: _NavigationShellApi(),
        offlineQueue: _NavigationZeroQueue(),
        onLogout: () {},
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Finder _bottomDestination(String label) =>
    find.byKey(ValueKey<String>('bottom-nav-$label'));

void _expectBottomDestination(
  WidgetTester tester,
  String label, {
  required bool selected,
}) {
  final finder = _bottomDestination(label);
  expect(finder, findsOneWidget);
  final node = tester.getSemantics(finder);
  expect(node.label, label);
  expect(node.getSemanticsData().hasFlag(ui.SemanticsFlag.isButton), isTrue);
  expect(
    node.getSemanticsData().hasFlag(ui.SemanticsFlag.isSelected),
    selected,
  );
  expect(tester.getSize(finder).height, greaterThanOrEqualTo(48));
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
                unawaited(
                  JiYiNavigator.pushDetail<void>(
                    context,
                    builder: (_) => const Scaffold(
                      body: Center(child: Text('detail')),
                    ),
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

    await tester.binding.handlePopRoute();
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
    await tester.pumpAndSettle();
    expect(find.text('记忆与人生'), findsOneWidget);
    expect(find.text('重要的人'), findsOneWidget);
    expect(find.text('我的人生'), findsOneWidget);

    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('重要的人和人生故事'), findsOneWidget);
    expect(find.text('记忆与人生'), findsNothing);
  });

  testWidgets('real AppShell exposes five accessible destinations and selection transitions',
      (tester) async {
    final semantics = tester.ensureSemantics();
    await _pumpNormalShell(tester);

    for (final label in ['今天', '记忆', '人生', '家庭', '我的']) {
      _expectBottomDestination(tester, label, selected: label == '今天');
    }

    await tester.tap(_bottomDestination('记忆'));
    await tester.pumpAndSettle();
    _expectBottomDestination(tester, '今天', selected: false);
    _expectBottomDestination(tester, '记忆', selected: true);

    await tester.tap(_bottomDestination('我的'));
    await tester.pumpAndSettle();
    _expectBottomDestination(tester, '记忆', selected: false);
    _expectBottomDestination(tester, '我的', selected: true);
    semantics.dispose();
  });

  testWidgets('real AppShell hides destinations during onboarding', (tester) async {
    final semantics = tester.ensureSemantics();
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: AppShell(
          api: _NavigationShellApi(authenticated: true),
          offlineQueue: _NavigationZeroQueue(),
          onboardingStore: _NavigationOnboardingStore(),
          startOnboarding: true,
          locationBridge: _NavigationUnavailableLocation(),
          motionSamplingBridge: _NavigationNoOpMotion(),
          onLogout: () {},
        ),
      ),
    );
    for (var frame = 0; frame < 20; frame += 1) {
      await tester.pump();
      if (find.byKey(const ValueKey('onboarding-intro')).evaluate().isNotEmpty) {
        break;
      }
    }

    for (final label in ['今天', '记忆', '人生', '家庭', '我的']) {
      expect(_bottomDestination(label), findsNothing);
    }
    semantics.dispose();
  });

  testWidgets('real AppShell hides destinations during account deletion',
      (tester) async {
    final semantics = tester.ensureSemantics();
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: AppShell(
          api: _NavigationShellApi(),
          offlineQueue: _NavigationZeroQueue(),
          resumeAccountDeletion: true,
          onLogout: () {},
        ),
      ),
    );
    await tester.pumpAndSettle();

    for (final label in ['今天', '记忆', '人生', '家庭', '我的']) {
      expect(_bottomDestination(label), findsNothing);
    }
    semantics.dispose();
  });
}
