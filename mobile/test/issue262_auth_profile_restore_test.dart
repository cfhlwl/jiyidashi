import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/widgets.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';
import 'package:jiyidashi/notification_client.dart';
import 'package:jiyidashi/motion_sampling_policy.dart';
import 'package:jiyidashi/native_location_bridge.dart';
import 'package:jiyidashi/native_motion_sampling_bridge.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/onboarding_state.dart';
import 'package:jiyidashi/stage1_app.dart';

const _owner = '11111111-1111-4111-8111-111111111111';
const _otherOwner = '22222222-2222-4222-8222-222222222222';

class _RestoreApi extends JiYiApiClient {
  _RestoreApi({required this.profileFailure, super.sessionStore})
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

class _RecordingNotifications extends _QuietNotifications {
  _RecordingNotifications(super.api);

  int terminalAuthLossCalls = 0;

  @override
  Future<void> onTerminalAuthLoss() async {
    terminalAuthLossCalls++;
  }
}

class _RecordingLocationBridge
    implements NativeLocationBridge, NativeLocationDiagnosticsBridge {
  static const _pausedStatus = NativeLocationStatus(
    supported: false,
    platform: 'TEST',
    permission: NativeLocationPermission.unknown,
    runtime: NativeLocationRuntime.paused,
    automaticEnabled: false,
    locationServicesEnabled: false,
  );

  int pauseCalls = 0;
  final List<String> diagnosticEvents = <String>[];
  final List<String> diagnosticReasons = <String>[];

  @override
  Future<NativeLocationStatus> status(String ownerUserId) async => _pausedStatus;

  @override
  Future<NativeLocationStatus> requestForegroundPermission(
    String ownerUserId,
  ) async => _pausedStatus;

  @override
  Future<NativeLocationStatus> enableAutomaticLocation(
    String ownerUserId,
  ) async => _pausedStatus;

  @override
  Future<NativeLocationStatus> openBackgroundLocationSettings(
    String ownerUserId,
  ) async => _pausedStatus;

  @override
  Future<NativeLocationStatus> openLocationServicesSettings(
    String ownerUserId,
  ) async => _pausedStatus;

  @override
  Future<NativeLocationStatus> disableAutomaticLocation(
    String ownerUserId,
  ) async => _pausedStatus;

  @override
  Future<NativeLocationStatus> start(String ownerUserId) async => _pausedStatus;

  @override
  Future<NativeLocationStatus> pause(String ownerUserId) async {
    pauseCalls++;
    return _pausedStatus;
  }

  @override
  Future<NativeLocationStatus> stop(String ownerUserId) async => _pausedStatus;

  @override
  Future<void> recordLocationLifecycleDiagnostic(
    String ownerUserId, {
    required String event,
    required String reason,
    String? result,
    bool? success,
  }) async {
    diagnosticEvents.add(event);
    diagnosticReasons.add(reason);
  }
}

class _DeferredRestoreApi extends _RestoreApi {
  _DeferredRestoreApi({this.lateProfileError})
      : super(
          profileFailure: null,
          sessionStore: MemoryAuthSessionStore(),
        );

  final Object? lateProfileError;
  final Completer<AuthRestoreStatus> restoreGate =
      Completer<AuthRestoreStatus>();
  final Completer<Map<String, dynamic>> profileGate =
      Completer<Map<String, dynamic>>();

  @override
  Future<AuthRestoreStatus> restorePersistedSession() async {
    refreshCalls++;
    final result = await restoreGate.future;
    if (result == AuthRestoreStatus.restored) {
      authenticatedUserId = _owner;
      accessToken = 'server-verified-access-a';
    }
    return result;
  }

  @override
  Future<Map<String, dynamic>> getProfile() async {
    profileCalls++;
    final profile = await profileGate.future;
    if (lateProfileError != null) throw lateProfileError!;
    return profile;
  }

  Future<void> switchToOtherOwner() async {
    await logout();
    authenticatedUserId = _otherOwner;
    accessToken = 'server-verified-access-b';
  }

  void completeProfile() {
    if (lateProfileError == null) {
      profileGate.complete(<String, dynamic>{'elder_mode_enabled': false});
    } else {
      profileGate.completeError(lateProfileError!);
    }
  }
}

class _BackoffRestoreApi extends _RestoreApi {
  _BackoffRestoreApi({required this.failuresBeforeRestore})
      : super(profileFailure: null);

  final int failuresBeforeRestore;

  @override
  Future<AuthRestoreStatus> restorePersistedSession() async {
    refreshCalls++;
    if (refreshCalls <= failuresBeforeRestore) {
      return AuthRestoreStatus.serverUnavailable;
    }
    return AuthRestoreStatus.restored;
  }
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

Future<void> _pumpApp(
  WidgetTester tester,
  JiYiApiClient api, {
  NativeLocationBridge? locationBridge,
  NotificationClientService? notificationClient,
}) async {
  await tester.pumpWidget(JiYiApp(
    api: api,
    offlineQueue: _EmptyQueue(),
    onboardingStore: _CompletedOnboarding(),
    locationBridge: locationBridge,
    notificationClient: notificationClient ?? _QuietNotifications(api),
    motionSamplingBridge: _IdleMotionBridge(),
  ));
  await tester.pump();
}

Future<void> _boot(WidgetTester tester, _RestoreApi api) async {
  await _pumpApp(tester, api);
  for (var attempt = 0; attempt < 120; attempt++) {
    await tester.pump(const Duration(milliseconds: 50));
    if (api.refreshCalls == 1 && api.profileCalls >= 1) {
      await tester.pump();
      return;
    }
  }
  throw TestFailure('cold-start session restore and profile were not reached');
}

Future<void> _waitFor(
  WidgetTester tester,
  bool Function() condition, {
  int attempts = 120,
}) async {
  for (var attempt = 0; attempt < attempts; attempt++) {
    if (condition()) return;
    await tester.pump(const Duration(milliseconds: 50));
  }
  throw TestFailure('condition was not reached');
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
    final location = _RecordingLocationBridge();
    final notifications = _RecordingNotifications(api);
    await _pumpApp(
      tester,
      api,
      locationBridge: location,
      notificationClient: notifications,
    );
    await _waitFor(tester, () => api.profileCalls >= 1);
    await tester.pump();
    expect(api.refreshCalls, 1);
    expect(find.byType(AppShell), findsNothing);
    expect(find.byType(AuthPage), findsOneWidget);
    expect(location.pauseCalls, 1);
    expect(location.diagnosticEvents, contains('pause'));
    expect(location.diagnosticReasons, contains('auth_session_terminal'));
    expect(notifications.terminalAuthLossCalls, 1);
  });

  testWidgets('profile successfully loaded after refresh retains shell', (tester) async {
    final api = _RestoreApi(profileFailure: null);
    await _boot(tester, api);
    expect(api.refreshCalls, 1);
    expect(find.byType(AppShell), findsOneWidget);
  });

  for (final lateError in <Object?>[
    null,
    ApiException(401, 'AUTH_SESSION_REVOKED'),
    TransportException('offline'),
  ]) {
    testWidgets(
      'late A profile result cannot mutate switched B session: '
      '${lateError?.runtimeType ?? 'success'}',
      (tester) async {
        final api = _DeferredRestoreApi(lateProfileError: lateError);
        final location = _RecordingLocationBridge();
        final notifications = _RecordingNotifications(api);
        await _pumpApp(
          tester,
          api,
          locationBridge: location,
          notificationClient: notifications,
        );
        expect(api.refreshCalls, 1);

        tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
        await tester.pump();
        expect(api.refreshCalls, 1);

        api.restoreGate.complete(AuthRestoreStatus.restored);
        await _waitFor(tester, () => api.profileCalls == 1);
        await api.switchToOtherOwner();
        api.completeProfile();
        await tester.pump();

        expect(api.authenticatedUserId, _otherOwner);
        expect(find.byType(AppShell), findsNothing);
        expect(find.byType(AuthPage), findsNothing);
        expect(location.pauseCalls, 0);
        expect(notifications.terminalAuthLossCalls, 0);
      },
    );
  }

  testWidgets('transient restore retries at every required backoff interval',
      (tester) async {
    final api = _BackoffRestoreApi(failuresBeforeRestore: 5);
    await _pumpApp(tester, api);
    expect(api.refreshCalls, 1);

    var expectedRefreshCalls = 1;
    for (final delay in <Duration>[
      const Duration(seconds: 3),
      const Duration(seconds: 6),
      const Duration(seconds: 12),
      const Duration(seconds: 24),
      const Duration(seconds: 60),
    ]) {
      await tester.pump(delay);
      await tester.pump();
      expectedRefreshCalls++;
      expect(api.refreshCalls, expectedRefreshCalls);
    }

    await _waitFor(tester, () => api.profileCalls >= 1);
    expect(api.refreshCalls, 6);
    expect(find.byType(AppShell), findsOneWidget);
  });

  testWidgets('app resume cancels backoff and retries immediately', (tester) async {
    final api = _BackoffRestoreApi(failuresBeforeRestore: 1);
    await _pumpApp(tester, api);
    expect(api.refreshCalls, 1);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    await _waitFor(tester, () => api.refreshCalls >= 2);
    await _waitFor(tester, () => api.profileCalls >= 1);

    expect(api.refreshCalls, 2);
    expect(find.byType(AppShell), findsOneWidget);
  });
}
