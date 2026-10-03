import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/motion_sampling_policy.dart';
import 'package:jiyidashi/native_location_bridge.dart';
import 'package:jiyidashi/native_motion_sampling_bridge.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/passive_memory_delivery.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const ownerA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const ownerB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const sampleUuid = '11111111-1111-4111-8111-111111111111';

class _PassiveApi extends JiYiApiClient {
  _PassiveApi() : super(baseUrl: 'https://core001.invalid/v1') {
    accessToken = 'access-a';
    authenticatedUserId = ownerA;
  }

  bool privacyPaused = false;
  bool privacyUnavailable = false;
  bool accountDeletionInProgress = false;
  bool transportFails = false;
  bool uploadUnauthorized = false;
  String uploadUnauthorizedCode = 'AUTH_SESSION_REVOKED';
  int refreshCalls = 0;
  int privacyCalls = 0;
  int uploadCalls = 0;
  Completer<void>? privacyGate;
  Completer<LocationBatchResult>? uploadGate;
  final List<List<String>> uploadedUuids = <List<String>>[];

  @override
  String? get authenticatedSessionId =>
      authenticatedUserId == ownerA
          ? 'session-a'
          : authenticatedUserId == ownerB
              ? 'session-b'
              : null;

  @override
  Future<bool> currentSessionMatchesSecureStorage() async =>
      authenticatedUserId == ownerA;

  @override
  Future<void> revalidateAuthenticatedOwnerAuthority() async {
    refreshCalls += 1;
    if (authenticatedUserId == null) {
      throw ApiException(401, 'INVALID_ACCESS_TOKEN');
    }
  }

  @override
  Future<Map<String, dynamic>> getProfile() async {
    if (accountDeletionInProgress) {
      throw ApiException(423, 'ACCOUNT_DELETION_IN_PROGRESS');
    }
    return <String, dynamic>{
      'id': authenticatedUserId,
      'elder_mode_enabled': false,
    };
  }

  @override
  Future<Map<String, dynamic>> getPrivacyStatus() async {
    privacyCalls += 1;
    if (privacyUnavailable) throw TransportException('privacy unavailable');
    await privacyGate?.future;
    return <String, dynamic>{
      'recording_paused': privacyPaused,
      'paused_until': null,
    };
  }

  @override
  Future<LocationBatchResult> uploadLocationBatch(
    List<LocationUploadPoint> points,
  ) async {
    uploadCalls += 1;
    uploadedUuids.add(
      points.map((point) => point.clientUuid).toList(growable: false),
    );
    if (transportFails) throw TransportException('response lost');
    if (uploadUnauthorized) throw ApiException(401, uploadUnauthorizedCode);
    final pending = uploadGate;
    if (pending != null) return pending.future;
    return LocationBatchResult(
      accepted: points.length,
      duplicates: 0,
      rejectedPrivacy: 0,
      rejectedFinalized: 0,
    );
  }
}

class _LocationBridge implements NativeLocationBridge {
  _LocationBridge({
    this.current = const NativeLocationStatus(
      supported: true,
      platform: 'test',
      permission: NativeLocationPermission.background,
      runtime: NativeLocationRuntime.stopped,
      automaticEnabled: true,
      locationServicesEnabled: true,
    ),
  });

  NativeLocationStatus current;
  int statusCalls = 0;
  int pauseCalls = 0;
  int startCalls = 0;

  @override
  Future<NativeLocationStatus> status(String ownerUserId) async {
    statusCalls += 1;
    return current;
  }

  @override
  Future<NativeLocationStatus> pause(String ownerUserId) async {
    pauseCalls += 1;
    current = NativeLocationStatus(
      supported: current.supported,
      platform: current.platform,
      permission: current.permission,
      runtime: NativeLocationRuntime.paused,
      automaticEnabled: current.automaticEnabled,
      locationServicesEnabled: current.locationServicesEnabled,
      restorePending: current.restorePending,
      queue: current.queue,
    );
    return current;
  }

  @override
  Future<NativeLocationStatus> start(String ownerUserId) async {
    startCalls += 1;
    current = NativeLocationStatus(
      supported: current.supported,
      platform: current.platform,
      permission: current.permission,
      runtime: NativeLocationRuntime.running,
      automaticEnabled: current.automaticEnabled,
      locationServicesEnabled: current.locationServicesEnabled,
      restorePending: false,
      queue: current.queue,
    );
    return current;
  }

  @override
  Future<NativeLocationStatus> requestForegroundPermission(String ownerUserId) async =>
      current;

  @override
  Future<NativeLocationStatus> enableAutomaticLocation(String ownerUserId) async =>
      current;

  @override
  Future<NativeLocationStatus> openBackgroundLocationSettings(String ownerUserId) async =>
      current;

  @override
  Future<NativeLocationStatus> openLocationServicesSettings(String ownerUserId) async =>
      current;

  @override
  Future<NativeLocationStatus> disableAutomaticLocation(String ownerUserId) async {
    current = NativeLocationStatus(
      supported: current.supported,
      platform: current.platform,
      permission: current.permission,
      runtime: NativeLocationRuntime.stopped,
      automaticEnabled: false,
      locationServicesEnabled: current.locationServicesEnabled,
      restorePending: false,
      queue: current.queue,
    );
    return current;
  }

  @override
  Future<NativeLocationStatus> stop(String ownerUserId) async => current;
}

class _SamplingBridge implements NativeMotionSamplingBridge {
  final controller = StreamController<void>.broadcast();
  final List<NativeLocationSample> samples = <NativeLocationSample>[];
  final List<List<String>> acknowledgements = <List<String>>[];
  int drainCalls = 0;
  int uploadMetricCalls = 0;

  @override
  Stream<void> get samplesAvailable => controller.stream;

  @override
  Future<List<NativeLocationSample>> drainSamples(
    String ownerUserId, {
    int limit = 100,
  }) async {
    drainCalls += 1;
    return samples.take(limit).toList(growable: false);
  }

  @override
  Future<void> acknowledgeSamples(
    String ownerUserId,
    List<String> clientUuids,
  ) async {
    acknowledgements.add(List<String>.of(clientUuids));
    samples.removeWhere((item) => clientUuids.contains(item.clientUuid));
  }

  @override
  Future<void> recordUploadBatch(
    String ownerUserId, {
    required int sampleCount,
  }) async {
    uploadMetricCalls += 1;
  }

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
  Future<void> purgeOwner(String ownerUserId) async {
    samples.clear();
  }

  @override
  Future<NativeMotionObservation?> takeObservation(String ownerUserId) async =>
      null;

  @override
  Future<void> close() async {
    await controller.close();
  }
}

NativeLocationSample sample() => sampleFor(sampleUuid);

NativeLocationSample sampleFor(
  String uuid, {
  int offsetSeconds = 0,
}) =>
    NativeLocationSample(
      clientUuid: uuid,
      latitude: 3.139 + (offsetSeconds / 100000),
      longitude: 101.6869 + (offsetSeconds / 100000),
      accuracyMeters: 18,
      speedMetersPerSecond: 1.2,
      recordedAt: DateTime.utc(2026, 10, 1, 2)
          .add(Duration(seconds: offsetSeconds)),
    );

void main() {
  sqfliteFfiInit();
  final factory = databaseFactoryFfiNoIsolate;
  late Directory tempDirectory;
  late String databasePath;
  late OfflineQueueStore store;

  setUp(() async {
    tempDirectory =
        await Directory.systemTemp.createTemp('jiyidashi-core001-delivery-');
    databasePath =
        '${tempDirectory.path}${Platform.pathSeparator}core001-delivery.sqlite3';
    store = OfflineQueueStore(
      factory: factory,
      databasePathProvider: () async => databasePath,
    );
  });

  tearDown(() async {
    await store.close();
    await factory.deleteDatabase(databasePath);
    if (await tempDirectory.exists()) {
      await tempDirectory.delete(recursive: true);
    }
  });

  test('account deletion authority blocks native drain and upload', () async {
    final api = _PassiveApi()..accountDeletionInProgress = true;
    final location = _LocationBridge();
    final sampling = _SamplingBridge()..samples.add(sample());
    final coordinator = PassiveMemoryDeliveryCoordinator(
      api: api,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    );

    final report = await coordinator.recoverAndDeliver();

    expect(
      report.status,
      PassiveMemoryRecoveryStatus.accountDeletionInProgress,
    );
    expect(location.statusCalls, 0);
    expect(sampling.drainCalls, 0);
    expect(api.uploadCalls, 0);
    expect(await store.countLocationSamples(ownerA), 0);
    await sampling.close();
  });

  test('fresh durable auth and privacy are required before native drain', () async {
    final api = _PassiveApi()..privacyUnavailable = true;
    final location = _LocationBridge();
    final sampling = _SamplingBridge()..samples.add(sample());
    final coordinator = PassiveMemoryDeliveryCoordinator(
      api: api,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    );

    final report = await coordinator.recoverAndDeliver();

    expect(report.status, PassiveMemoryRecoveryStatus.privacyUnavailable);
    expect(api.refreshCalls, 1);
    expect(api.privacyCalls, 1);
    expect(sampling.drainCalls, 0);
    expect(api.uploadCalls, 0);
    expect(await store.countLocationSamples(ownerA), 0);
    await sampling.close();
  });

  test('native UUID is committed to SQLite before ack and deleted only after server receipt',
      () async {
    final api = _PassiveApi();
    final location = _LocationBridge();
    final sampling = _SamplingBridge()..samples.add(sample());
    final coordinator = PassiveMemoryDeliveryCoordinator(
      api: api,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    );

    final report = await coordinator.recoverAndDeliver();

    expect(report.status, PassiveMemoryRecoveryStatus.delivered);
    expect(report.nativeHandedOff, 1);
    expect(report.deliveryCompleted, 1);
    expect(sampling.acknowledgements, <List<String>>[
      <String>[sampleUuid],
    ]);
    expect(api.uploadedUuids, <List<String>>[
      <String>[sampleUuid],
    ]);
    expect(await store.countLocationSamples(ownerA), 0);
    final diagnostics = await store.locationQueueDiagnostics(ownerA);
    expect(diagnostics.lastDeliveryAt, isNotNull);
    await sampling.close();
  });

  test('terminal upload 401 pauses producer without clearing enabled preference',
      () async {
    final api = _PassiveApi()..uploadUnauthorized = true;
    final location = _LocationBridge(
      current: const NativeLocationStatus(
        supported: true,
        platform: 'test',
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.running,
        automaticEnabled: true,
        locationServicesEnabled: true,
      ),
    );
    final sampling = _SamplingBridge()..samples.add(sample());
    final coordinator = PassiveMemoryDeliveryCoordinator(
      api: api,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    );

    final report = await coordinator.recoverAndDeliver();

    expect(report.status, PassiveMemoryRecoveryStatus.noSession);
    expect(location.current.runtime, NativeLocationRuntime.paused);
    expect(location.current.automaticEnabled, isTrue);
    expect((await store.listLocationSamples(ownerA)).single.clientUuid, sampleUuid);
    await sampling.close();
  });

  test('response loss preserves the same UUID for a later replay', () async {
    final api = _PassiveApi()..transportFails = true;
    final location = _LocationBridge();
    final sampling = _SamplingBridge()..samples.add(sample());
    final coordinator = PassiveMemoryDeliveryCoordinator(
      api: api,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    );

    final first = await coordinator.recoverAndDeliver();
    expect(first.status, PassiveMemoryRecoveryStatus.retryableFailure);
    expect((await store.listLocationSamples(ownerA)).single.clientUuid, sampleUuid);
    expect(sampling.samples, isEmpty);

    api.transportFails = false;
    final second = await coordinator.recoverAndDeliver();
    expect(second.status, PassiveMemoryRecoveryStatus.delivered);
    expect(api.uploadedUuids, <List<String>>[
      <String>[sampleUuid],
      <String>[sampleUuid],
    ]);
    expect(await store.countLocationSamples(ownerA), 0);
    await sampling.close();
  });

  test('SQLite capacity ACKs only committed native samples and leaves overflow durable',
      () async {
    await store.close();
    store = OfflineQueueStore(
      factory: factory,
      databasePathProvider: () async => databasePath,
      locationQueueCapacityPerOwner: 1,
    );
    const secondUuid = '22222222-2222-4222-8222-222222222222';
    final api = _PassiveApi()..transportFails = true;
    final location = _LocationBridge();
    final sampling = _SamplingBridge()
      ..samples.add(sample())
      ..samples.add(sampleFor(secondUuid, offsetSeconds: 1));
    final coordinator = PassiveMemoryDeliveryCoordinator(
      api: api,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    );

    final report = await coordinator.recoverAndDeliver();

    expect(report.status, PassiveMemoryRecoveryStatus.retryableFailure);
    expect(report.nativeHandedOff, 1);
    expect(sampling.acknowledgements, <List<String>>[
      <String>[sampleUuid],
    ]);
    expect(sampling.samples.map((item) => item.clientUuid), <String>[secondUuid]);
    final queued = await store.listLocationSamples(ownerA);
    expect(queued.map((item) => item.clientUuid), <String>[sampleUuid]);
    final diagnostics = await store.locationQueueDiagnostics(ownerA);
    expect(diagnostics.queueDepth, 1);
    expect(diagnostics.queueCapacity, 1);
    expect(diagnostics.capacityPressure, isTrue);
    await sampling.close();
  });

  test('late privacy PASS from owner A cannot authorize drain after account switch',
      () async {
    final privacyGate = Completer<void>();
    final api = _PassiveApi()..privacyGate = privacyGate;
    final location = _LocationBridge();
    final sampling = _SamplingBridge()..samples.add(sample());
    final coordinator = PassiveMemoryDeliveryCoordinator(
      api: api,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    );

    final pending = coordinator.recoverAndDeliver();
    await Future<void>.delayed(Duration.zero);
    api.authenticatedUserId = ownerB;
    privacyGate.complete();

    final report = await pending;
    expect(report.status, PassiveMemoryRecoveryStatus.authorityChanged);
    expect(sampling.drainCalls, 0);
    expect(api.uploadCalls, 0);
    expect(await store.countLocationSamples(ownerA), 0);
    await sampling.close();
  });

  test('late upload success after owner switch keeps local replay proof', () async {
    final uploadGate = Completer<LocationBatchResult>();
    final api = _PassiveApi()..uploadGate = uploadGate;
    final location = _LocationBridge();
    final sampling = _SamplingBridge()..samples.add(sample());
    final coordinator = PassiveMemoryDeliveryCoordinator(
      api: api,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    );

    final pending = coordinator.recoverAndDeliver();
    while (api.uploadCalls == 0) {
      await Future<void>.delayed(Duration.zero);
    }
    api.authenticatedUserId = ownerB;
    uploadGate.complete(
      const LocationBatchResult(
        accepted: 1,
        duplicates: 0,
        rejectedPrivacy: 0,
        rejectedFinalized: 0,
      ),
    );

    final report = await pending;
    expect(report.status, PassiveMemoryRecoveryStatus.authorityChanged);
    expect((await store.listLocationSamples(ownerA)).single.clientUuid, sampleUuid);
    await sampling.close();
  });

  test('two coordinators share the SQLite lease and cannot double-send', () async {
    final uploadGate = Completer<LocationBatchResult>();
    final firstApi = _PassiveApi()..uploadGate = uploadGate;
    final secondApi = _PassiveApi();
    final location = _LocationBridge();
    final sampling = _SamplingBridge()..samples.add(sample());
    final first = PassiveMemoryDeliveryCoordinator(
      api: firstApi,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    );
    final second = PassiveMemoryDeliveryCoordinator(
      api: secondApi,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    );

    final firstPending = first.recoverAndDeliver();
    while (firstApi.uploadCalls == 0) {
      await Future<void>.delayed(Duration.zero);
    }
    final secondReport = await second.recoverAndDeliver();

    expect(secondReport.status, PassiveMemoryRecoveryStatus.busy);
    expect(secondApi.uploadCalls, 0);

    uploadGate.complete(
      const LocationBatchResult(
        accepted: 1,
        duplicates: 0,
        rejectedPrivacy: 0,
        rejectedFinalized: 0,
      ),
    );
    expect(
      (await firstPending).status,
      PassiveMemoryRecoveryStatus.delivered,
    );
    await sampling.close();
  });

  test('privacy quarantine resumes producer only after a later fresh PASS',
      () async {
    final api = _PassiveApi()..privacyPaused = true;
    final location = _LocationBridge(
      current: const NativeLocationStatus(
        supported: true,
        platform: 'test',
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.paused,
        automaticEnabled: true,
        locationServicesEnabled: true,
        restorePending: true,
      ),
    );
    final sampling = _SamplingBridge();
    final coordinator = PassiveMemoryDeliveryCoordinator(
      api: api,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    );

    final paused = await coordinator.recoverAndDeliver();
    expect(paused.status, PassiveMemoryRecoveryStatus.privacyPaused);
    expect(location.startCalls, 0);
    expect(location.current.restorePending, isTrue);

    api.privacyPaused = false;
    final recovered = await coordinator.recoverAndDeliver();
    expect(recovered.status, PassiveMemoryRecoveryStatus.noWork);
    expect(location.startCalls, 1);
    expect(location.current.runtime, NativeLocationRuntime.running);
    await sampling.close();
  });

  test('authoritative pause stops native recovery and keeps queued data unsent',
      () async {
    final api = _PassiveApi()..privacyPaused = true;
    final location = _LocationBridge();
    final sampling = _SamplingBridge()..samples.add(sample());
    final coordinator = PassiveMemoryDeliveryCoordinator(
      api: api,
      store: store,
      locationBridge: location,
      samplingBridge: sampling,
    );

    final report = await coordinator.recoverAndDeliver();

    expect(report.status, PassiveMemoryRecoveryStatus.privacyPaused);
    expect(location.pauseCalls, 1);
    expect(sampling.drainCalls, 0);
    expect(api.uploadCalls, 0);
    await sampling.close();
  });
}
