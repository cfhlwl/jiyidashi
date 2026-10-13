import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/notification_client.dart';
import 'package:jiyidashi/motion_sampling_policy.dart';
import 'package:jiyidashi/native_motion_sampling_bridge.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/onboarding_state.dart';
import 'package:jiyidashi/stage1_app.dart';

const _owner = '11111111-1111-4111-8111-111111111111';

class _RestoreApi extends JiYiApiClient {
  _RestoreApi({required this.profileFailure})
      : super(baseUrl: 'https://issue262.invalid/v1') {
    authenticatedUserId = _owner;
    accessToken = 'server-verified-access';
  }

  final Object? profileFailure;
  int refreshCalls = 0;
  int profileCalls = 0;

  @override
  Future<AuthRestoreStatus> restorePersistedSession() async {
    refreshCalls++;
    return AuthRestoreStatus.restored;
  }

  @override
  Future<Map<String, dynamic>> getProfile() async {
    profileCalls++;
    if (profileFailure != null) throw profileFailure!;
    return {'elder_mode_enabled': false};
  }

  @override
  Future<Map<String, dynamic>> getPrivacyStatus() async =>
      {'recording_paused': true, 'paused_until': null};
}

class _QuietNotifications extends NotificationClientService {
  _QuietNotifications(JiYiApiClient api) : super(api: api);

  @override
  Future<void> initialize() async {}

  @override
  Future<void> onAuthenticated() async {}

  @override
  Future<void> onTerminalAuthLoss() async {}

  @override
  Future<void> onAppResumed() async {}
}

class _IdleMotionBridge implements NativeMotionSamplingBridge {
  final StreamController<void> _events = StreamController<void>.broadcast();

  @override
  Stream<void> get samplesAvailable => _events.stream;

  @override
  Future<List<NativeLocationSample>> drainSamples(
    String ownerUserId, {int limit = 100,
  }) async => const <NativeLocationSample>[];

  @override
  Future<NativeMotionObservation?> takeObservation(String ownerUserId) async => null;

  @override
  Future<void> acknowledgeSamples(String ownerUserId, List<String> clientUuids) async {}

  @override
  Future<void> applyProfile(String ownerUserId, AdaptiveSamplingProfile profile) async {}

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
  Future<void> recordUploadBatch(String ownerUserId, {required int sampleCount}) async {}

  @override
  Future<void> purgeOwner(String ownerUserId) async {}

  @override
  Future<void> close() async { await _events.close(); }
}

class _EmptyQueue extends OfflineQueueStore {
  @override
  Future<int> countAwaitingDelivery(String ownerUserId) async => 0;

  @override
  Future<void> close() async {}
}

class _CompletedOnboarding implements OnboardingStateStore {
  @override
  Future<OnboardingStatus?> read(String ownerUserId) async =>
      OnboardingStatus.completed;
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

Future<void> _boot(WidgetTester tester, _RestoreApi api) async {
  await tester.pumpWidget(JiYiApp(
    api: api,
    offlineQueue: _EmptyQueue(),
    onboardingStore: _CompletedOnboarding(),
    notificationClient: _QuietNotifications(api),
    motionSamplingBridge: _IdleMotionBridge(),
  ));
  for (var attempt = 0; attempt < 120; attempt++) {
    await tester.pump(const Duration(milliseconds: 50));
    if (api.refreshCalls == 1 && api.profileCalls >= 1) {
      await tester.pump();
      return;
    }
  }
  throw TestFailure('cold-start session restore and profile were not reached');
}

void main() {
  for (final error in <Object>[
    TransportException('offline'),
    ApiException(503, 'SERVER_TEMPORARILY_UNAVAILABLE'),
    ProtocolException('profile response unavailable'),
  ]) {
    testWidgets(
      'successful refresh keeps shell authenticated after nonterminal profile error: ${error.runtimeType}',
      (tester) async {
        final api = _RestoreApi(profileFailure: error);
        await _boot(tester, api);

        // These failures occur after server refresh succeeded. They are not proof
        // of session revoke/expiry and must never show the login page.
        expect(api.refreshCalls, 1);
        // The authenticated AppShell also loads profile/elder mode. Both reads
        // are legitimate; only token rotation/restore must remain single-flight.
        expect(api.profileCalls, greaterThanOrEqualTo(1));
        expect(find.byType(AppShell), findsOneWidget);
      },
    );
  }

  testWidgets('terminal profile authority failure still signs out', (tester) async {
    final api = _RestoreApi(
      profileFailure: ApiException(401, 'AUTH_SESSION_REVOKED'),
    );
    await _boot(tester, api);
    expect(api.refreshCalls, 1);
    expect(find.byType(AppShell), findsNothing);
  });

  testWidgets('profile successfully loaded after refresh retains shell', (tester) async {
    final api = _RestoreApi(profileFailure: null);
    await _boot(tester, api);
    expect(api.refreshCalls, 1);
    expect(find.byType(AppShell), findsOneWidget);
  });
}
