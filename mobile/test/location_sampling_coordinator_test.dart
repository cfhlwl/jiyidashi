import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/location_sampling_coordinator.dart';
import 'package:jiyidashi/motion_sampling_policy.dart';
import 'package:jiyidashi/native_location_bridge.dart';
import 'package:jiyidashi/native_location_controller.dart';
import 'package:jiyidashi/native_motion_sampling_bridge.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

class _LocationBridge implements NativeLocationBridge {
  _LocationBridge({required this.current});

  NativeLocationStatus current;
  final List<String> calls = <String>[];

  @override
  Future<NativeLocationStatus> status(String ownerUserId) async {
    calls.add('status');
    return current;
  }

  @override
  Future<NativeLocationStatus> requestForegroundPermission(
    String ownerUserId,
  ) async =>
      current;

  @override
  Future<NativeLocationStatus> enableAutomaticLocation(
    String ownerUserId,
  ) async =>
      current;

  @override
  Future<NativeLocationStatus> openBackgroundLocationSettings(
    String ownerUserId,
  ) async =>
      current;

  @override
  Future<NativeLocationStatus> disableAutomaticLocation(
    String ownerUserId,
  ) async {
    calls.add('disable');
    current = _status(runtime: NativeLocationRuntime.stopped);
    return current;
  }

  @override
  Future<NativeLocationStatus> start(String ownerUserId) async {
    calls.add('start');
    current = _status(runtime: NativeLocationRuntime.running);
    return current;
  }

  @override
  Future<NativeLocationStatus> pause(String ownerUserId) async {
    calls.add('pause');
    current = _status(runtime: NativeLocationRuntime.paused);
    return current;
  }

  @override
  Future<NativeLocationStatus> stop(String ownerUserId) async {
    calls.add('stop');
    current = _status(runtime: NativeLocationRuntime.stopped);
    return current;
  }

  static NativeLocationStatus _status({
    required NativeLocationRuntime runtime,
  }) =>
      NativeLocationStatus(
        supported: true,
        platform: 'test',
        permission: NativeLocationPermission.background,
        runtime: runtime,
        automaticEnabled: true,
        locationServicesEnabled: true,
      );
}

class _SamplingBridge implements NativeMotionSamplingBridge {
  final controller = StreamController<void>.broadcast();
  final List<NativeLocationSample> samples = <NativeLocationSample>[];
  final List<List<String>> acknowledgements = <List<String>>[];
  final List<AdaptiveSamplingProfile> profiles = <AdaptiveSamplingProfile>[];
  NativeMotionObservation? observation;
  int observationCalls = 0;
  int drainCalls = 0;
  int uploadBatches = 0;
  int uploadedSamples = 0;
  int purgeCalls = 0;

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
  Future<NativeMotionObservation?> takeObservation(String ownerUserId) async {
    observationCalls += 1;
    final current = observation;
    observation = null;
    return current;
  }

  @override
  Future<void> acknowledgeSamples(
    String ownerUserId,
    List<String> clientUuids,
  ) async {
    acknowledgements.add(List<String>.of(clientUuids));
    samples.removeWhere((sample) => clientUuids.contains(sample.clientUuid));
  }

  @override
  Future<void> applyProfile(
    String ownerUserId,
    AdaptiveSamplingProfile profile,
  ) async {
    profiles.add(profile);
  }

  @override
  Future<LocationProducerMetrics> metrics(String ownerUserId) async =>
      const LocationProducerMetrics(
        wakeups: 7,
        samplesAccepted: 4,
        samplesDropped: 1,
        uploadBatches: 2,
        uploadedSamples: 3,
        activeTrackingDuration: Duration(minutes: 8),
      );

  @override
  Future<void> recordUploadBatch(
    String ownerUserId, {
    required int sampleCount,
  }) async {
    uploadBatches += 1;
    uploadedSamples += sampleCount;
  }

  @override
  Future<void> purgeOwner(String ownerUserId) async {
    purgeCalls += 1;
    samples.clear();
  }

  @override
  Future<void> close() async {
    await controller.close();
  }
}

class _BlockingPurgeSamplingBridge extends _SamplingBridge {
  final Completer<void> purgeEntered = Completer<void>();
  final Completer<void> releasePurge = Completer<void>();

  @override
  Future<void> purgeOwner(String ownerUserId) async {
    purgeCalls += 1;
    if (!purgeEntered.isCompleted) purgeEntered.complete();
    await releasePurge.future;
  }
}

class _SamplingApi extends JiYiApiClient {
  _SamplingApi() : super(baseUrl: 'https://sampling.invalid/v1') {
    accessToken = 'sampling-token';
    authenticatedUserId = owner;
  }

  bool paused = false;
  bool privacyThrows = false;
  int privacyCalls = 0;
  int uploadCalls = 0;
  bool transportFails = false;
  bool pauseRace409 = false;
  int future422Remaining = 0;
  final List<List<String>> uploadedUuidBatches = <List<String>>[];

  @override
  Future<Map<String, dynamic>> getPrivacyStatus() async {
    privacyCalls += 1;
    if (privacyThrows) throw TransportException('privacy unavailable');
    return <String, dynamic>{
      'recording_paused': paused,
      'paused_until': null,
    };
  }

  @override
  Future<LocationBatchResult> uploadLocationBatch(
    List<LocationUploadPoint> points,
  ) async {
    uploadCalls += 1;
    uploadedUuidBatches.add(
      points.map((point) => point.clientUuid).toList(growable: false),
    );
    if (transportFails) throw TransportException('response lost');
    if (pauseRace409) throw ApiException(409, 'RECORDING_PAUSED');
    if (future422Remaining > 0) {
      future422Remaining -= 1;
      throw ApiException(422, 'LOCATION_RECORDED_AT_IN_FUTURE');
    }
    return LocationBatchResult(
      accepted: points.length,
      duplicates: 0,
      rejectedPrivacy: 0,
      rejectedFinalized: 0,
    );
  }
}

void main() {
  sqfliteFfiInit();
  final factory = databaseFactoryFfiNoIsolate;
  late Directory tempDirectory;
  late String databasePath;
  late OfflineQueueStore store;

  NativeLocationStatus runningStatus() => const NativeLocationStatus(
        supported: true,
        platform: 'test',
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.running,
        automaticEnabled: true,
        locationServicesEnabled: true,
      );

  setUp(() async {
    tempDirectory =
        await Directory.systemTemp.createTemp('jiyidashi-sampling-');
    databasePath =
        '${tempDirectory.path}${Platform.pathSeparator}sampling.sqlite3';
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

  Future<NativeLocationController> activeController(
    _LocationBridge bridge,
  ) async {
    final controller = NativeLocationController(
      bridge: bridge,
      ownerUserId: owner,
    );
    await controller.initialize();
    controller.markPrivacyActive();
    return controller;
  }

  NativeLocationSample sample(String uuid) => NativeLocationSample(
        clientUuid: uuid,
        latitude: 3.139,
        longitude: 101.6869,
        accuracyMeters: 18,
        speedMetersPerSecond: 1.5,
        recordedAt: DateTime.utc(2026, 9, 20, 1),
      );

  test('privacy unknown prevents native drain and upload', () async {
    final locationBridge = _LocationBridge(current: runningStatus());
    final controller = NativeLocationController(
      bridge: locationBridge,
      ownerUserId: owner,
    );
    await controller.initialize();
    final native = _SamplingBridge()..samples.add(sample('sample-unknown'));
    final api = _SamplingApi();
    final coordinator = LocationSamplingCoordinator(
      api: api,
      store: store,
      locationController: controller,
      nativeBridge: native,
    );

    await coordinator.start();

    expect(native.drainCalls, 0);
    expect(api.uploadCalls, 0);
    expect(await store.countLocationSamples(owner), 0);
    coordinator.dispose();
    controller.dispose();
  });

  test('known privacy pause prevents native drain and upload', () async {
    final locationBridge = _LocationBridge(current: runningStatus());
    final controller = await activeController(locationBridge);
    await controller.pauseForPrivacy();
    final native = _SamplingBridge()..samples.add(sample('sample-paused'));
    final api = _SamplingApi();
    final coordinator = LocationSamplingCoordinator(
      api: api,
      store: store,
      locationController: controller,
      nativeBridge: native,
    );

    await coordinator.start();

    expect(native.drainCalls, 0);
    expect(api.uploadCalls, 0);
    expect(await store.countLocationSamples(owner), 0);
    coordinator.dispose();
    controller.dispose();
  });

  test('SQLite commit precedes native ack and authoritative success deletes row', () async {
    final locationBridge = _LocationBridge(current: runningStatus());
    final controller = await activeController(locationBridge);
    const uuid = '21212121-2121-4212-8212-212121212121';
    final native = _SamplingBridge()..samples.add(sample(uuid));
    final api = _SamplingApi();
    final coordinator = LocationSamplingCoordinator(
      api: api,
      store: store,
      locationController: controller,
      nativeBridge: native,
    );

    await coordinator.start();

    expect(native.acknowledgements, <List<String>>[
      <String>[uuid],
    ]);
    expect(api.uploadedUuidBatches, <List<String>>[
      <String>[uuid],
    ]);
    expect(await store.countLocationSamples(owner), 0);
    expect(native.uploadBatches, 1);
    expect(native.uploadedSamples, 1);
    expect(coordinator.motionState, MotionState.walking);
    coordinator.dispose();
    controller.dispose();
  });

  test('poor quality observation backs off walking even when raw fix is dropped',
      () async {
    final locationBridge = _LocationBridge(current: runningStatus());
    final controller = await activeController(locationBridge);
    final native = _SamplingBridge()
      ..observation = NativeMotionObservation(
        recordedAt: DateTime.utc(2026, 9, 20, 1),
        accuracyMeters: 120,
        speedMetersPerSecond: 1.5,
      );
    final api = _SamplingApi();
    final coordinator = LocationSamplingCoordinator(
      api: api,
      store: store,
      locationController: controller,
      nativeBridge: native,
      motionStateMachine: MotionStateMachine(
        initialState: MotionState.walking,
      ),
    );

    await coordinator.start();

    // [人工注释][S2-004/005] The poor raw point never enters SQLite, yet its
    // coordinate-free observation must make the next walking profile back off.
    expect(await store.countLocationSamples(owner), 0);
    expect(coordinator.motionState, MotionState.walking);
    expect(coordinator.profile.minInterval, const Duration(minutes: 2));
    expect(coordinator.profile.minDistanceMeters, 60);
    expect(native.profiles.last, coordinator.profile);
    coordinator.dispose();
    controller.dispose();
  });

  test('future timestamp 422 remains deliverable and retries the same UUID',
      () async {
    final locationBridge = _LocationBridge(current: runningStatus());
    final controller = await activeController(locationBridge);
    const uuid = '27212121-2121-4212-8212-212121212121';
    final native = _SamplingBridge()..samples.add(sample(uuid));
    final api = _SamplingApi()..future422Remaining = 1;
    final coordinator = LocationSamplingCoordinator(
      api: api,
      store: store,
      locationController: controller,
      nativeBridge: native,
    );

    await coordinator.start();

    expect(await store.countLocationSamples(owner), 1);
    expect(
      (await store.listLocationSamples(owner)).single.clientUuid,
      uuid,
      reason: 'FUTURE 422 must not write blocked_error',
    );

    await coordinator.pump(forceFlush: true);

    expect(await store.countLocationSamples(owner), 0);
    expect(api.uploadedUuidBatches, <List<String>>[
      <String>[uuid],
      <String>[uuid],
    ]);
    coordinator.dispose();
    controller.dispose();
  });

  test('response loss keeps SQLite row and retries the same client UUID', () async {
    final locationBridge = _LocationBridge(current: runningStatus());
    final controller = await activeController(locationBridge);
    const uuid = '22212121-2121-4212-8212-212121212121';
    final native = _SamplingBridge()..samples.add(sample(uuid));
    final api = _SamplingApi()..transportFails = true;
    final coordinator = LocationSamplingCoordinator(
      api: api,
      store: store,
      locationController: controller,
      nativeBridge: native,
    );

    await coordinator.start();
    expect(await store.countLocationSamples(owner), 1);
    expect(native.samples, isEmpty);
    expect(api.uploadedUuidBatches.single, <String>[uuid]);

    api.transportFails = false;
    await coordinator.pump(forceFlush: true);

    expect(await store.countLocationSamples(owner), 0);
    expect(api.uploadedUuidBatches, <List<String>>[
      <String>[uuid],
      <String>[uuid],
    ]);
    coordinator.dispose();
    controller.dispose();
  });

  test('authoritative server pause blocks queued upload and pauses producer', () async {
    final locationBridge = _LocationBridge(current: runningStatus());
    final controller = await activeController(locationBridge);
    const uuid = '23212121-2121-4212-8212-212121212121';
    final native = _SamplingBridge()..samples.add(sample(uuid));
    final api = _SamplingApi()..paused = true;
    final coordinator = LocationSamplingCoordinator(
      api: api,
      store: store,
      locationController: controller,
      nativeBridge: native,
    );

    await coordinator.start();

    expect(api.uploadCalls, 0);
    expect(await store.countLocationSamples(owner), 1);
    expect(controller.privacyGate, NativeLocationPrivacyGate.paused);
    expect(locationBridge.calls, contains('pause'));
    coordinator.dispose();
    controller.dispose();
  });

  test('server pause race after preflight preserves UUID and pauses producer', () async {
    final locationBridge = _LocationBridge(current: runningStatus());
    final controller = await activeController(locationBridge);
    const uuid = '25212121-2121-4212-8212-212121212121';
    final native = _SamplingBridge()..samples.add(sample(uuid));
    final api = _SamplingApi()..pauseRace409 = true;
    final coordinator = LocationSamplingCoordinator(
      api: api,
      store: store,
      locationController: controller,
      nativeBridge: native,
    );

    await coordinator.start();

    expect(api.uploadCalls, 1);
    expect(await store.countLocationSamples(owner), 1);
    expect(
      (await store.listLocationSamples(owner)).single.clientUuid,
      uuid,
    );
    expect(controller.privacyGate, NativeLocationPrivacyGate.paused);
    expect(locationBridge.calls, contains('pause'));
    coordinator.dispose();
    controller.dispose();
  });

  test('privacy lookup failure blocks upload and converges gate to unknown', () async {
    final locationBridge = _LocationBridge(current: runningStatus());
    final controller = await activeController(locationBridge);
    const uuid = '24212121-2121-4212-8212-212121212121';
    final native = _SamplingBridge()..samples.add(sample(uuid));
    final api = _SamplingApi()..privacyThrows = true;
    final coordinator = LocationSamplingCoordinator(
      api: api,
      store: store,
      locationController: controller,
      nativeBridge: native,
    );

    await coordinator.start();

    expect(api.uploadCalls, 0);
    expect(await store.countLocationSamples(owner), 1);
    expect(controller.privacyGate, NativeLocationPrivacyGate.unknown);
    expect(locationBridge.calls, contains('pause'));
    coordinator.dispose();
    controller.dispose();
  });

  test('account deletion quiesce seals later pumps before native purge completes', () async {
    final locationBridge = _LocationBridge(current: runningStatus());
    final controller = await activeController(locationBridge);
    final native = _BlockingPurgeSamplingBridge();
    final api = _SamplingApi();
    final coordinator = LocationSamplingCoordinator(
      api: api,
      store: store,
      locationController: controller,
      nativeBridge: native,
    );

    await coordinator.start();
    final drainsBeforeDelete = native.drainCalls;

    // [人工注释][S1-022][S2-004/005] quiesce() 在首个 await 前先置本地 gate；
    // 即使 native purge 仍被阻塞，后续生命周期 pump 也必须立即变成 no-op。
    final deleting = coordinator.quiesceForAccountDeletion();
    await native.purgeEntered.future;
    await coordinator.pump(forceFlush: true);

    expect(native.drainCalls, drainsBeforeDelete);
    expect(api.uploadCalls, 0);
    expect(await store.countLocationSamples(owner), 0);

    native.releasePurge.complete();
    await deleting;
    coordinator.dispose();
    controller.dispose();
  });

  test('metrics snapshot contains counters and duration without location payload', () async {
    final locationBridge = _LocationBridge(current: runningStatus());
    final controller = await activeController(locationBridge);
    final native = _SamplingBridge();
    final api = _SamplingApi();
    final coordinator = LocationSamplingCoordinator(
      api: api,
      store: store,
      locationController: controller,
      nativeBridge: native,
    );

    await coordinator.start();

    final metrics = coordinator.snapshot.metrics;
    expect(metrics.wakeups, 7);
    expect(metrics.samplesAccepted, 4);
    expect(metrics.samplesDropped, 1);
    expect(metrics.uploadBatches, 2);
    expect(metrics.activeTrackingDuration, const Duration(minutes: 8));
    expect(
      LocationProducerMetrics.fromPlatform(<String, Object?>{
        'wakeups': 1,
        'latitude': 3.139,
        'longitude': 101.6869,
      }).wakeups,
      1,
      reason: 'metrics parser ignores any location-shaped extra fields',
    );
    coordinator.dispose();
    controller.dispose();
  });
}
