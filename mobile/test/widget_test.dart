import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';
import 'package:jiyidashi/main.dart';
import 'package:jiyidashi/motion_sampling_policy.dart';
import 'package:jiyidashi/native_motion_sampling_bridge.dart';

class _ControlledRestoreApi extends JiYiApiClient {
  _ControlledRestoreApi(this.restoreResult)
      : super(
          baseUrl: 'https://example.test/v1',
          sessionStore: MemoryAuthSessionStore(),
        );

  final Future<AuthRestoreStatus> restoreResult;
  int restoreCallCount = 0;

  @override
  Future<AuthRestoreStatus> restorePersistedSession() {
    restoreCallCount += 1;
    return restoreResult;
  }
}

class _NoOpMotionSamplingBridge implements NativeMotionSamplingBridge {
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

void main() {
  testWidgets('shows formal authentication before personal memory space', (tester) async {
    final restore = Completer<AuthRestoreStatus>();
    final api = _ControlledRestoreApi(restore.future);

    await tester.pumpWidget(
      JiYiApp(
        api: api,
        motionSamplingBridge: _NoOpMotionSamplingBridge(),
      ),
    );

    for (var attempt = 0; attempt < 10 && api.restoreCallCount == 0; attempt++) {
      await tester.pump();
    }

    // Cold start must remain neutral while the server-authoritative restore is pending.
    expect(api.restoreCallCount, 1);
    expect(find.bySemanticsLabel('迹忆'), findsOneWidget);
    expect(find.text('邮箱登录'), findsNothing);
    expect(find.text('今天'), findsNothing);

    // Resolve the same transition explicitly; do not depend on wall-clock timing or
    // the real session store to make the signed-out state observable.
    restore.complete(AuthRestoreStatus.noPersistedSession);
    await tester.pump();
    await tester.pumpAndSettle();

    expect(find.text('邮箱登录'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('auth-v3-register-entry')),
      findsOneWidget,
    );
    expect(find.text('今天'), findsNothing);
  });
}
