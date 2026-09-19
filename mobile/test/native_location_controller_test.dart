import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/native_location_bridge.dart';
import 'package:jiyidashi/native_location_controller.dart';

const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

NativeLocationStatus _status({
  NativeLocationPermission permission = NativeLocationPermission.notDetermined,
  NativeLocationRuntime runtime = NativeLocationRuntime.stopped,
  bool automaticEnabled = false,
  bool servicesEnabled = true,
  String? reason,
}) {
  return NativeLocationStatus(
    supported: true,
    platform: 'test',
    permission: permission,
    runtime: runtime,
    automaticEnabled: automaticEnabled,
    locationServicesEnabled: servicesEnabled,
    reason: reason,
  );
}

class _FakeBridge implements NativeLocationBridge {
  final List<String> calls = <String>[];

  NativeLocationStatus current = _status();
  NativeLocationStatus? foregroundResult;
  NativeLocationStatus? enableResult;
  NativeLocationStatus? startResult;
  NativeLocationStatus? pauseResult;
  NativeLocationStatus? stopResult;
  NativeLocationStatus? disableResult;
  Completer<NativeLocationStatus>? foregroundCompleter;

  @override
  Future<NativeLocationStatus> status(String ownerUserId) async {
    calls.add('status');
    return current;
  }

  @override
  Future<NativeLocationStatus> requestForegroundPermission(
    String ownerUserId,
  ) {
    calls.add('requestForegroundPermission');
    final pending = foregroundCompleter;
    if (pending != null) return pending.future;
    current = foregroundResult ?? current;
    return Future<NativeLocationStatus>.value(current);
  }

  @override
  Future<NativeLocationStatus> enableAutomaticLocation(String ownerUserId) async {
    calls.add('enableAutomaticLocation');
    current = enableResult ?? current;
    return current;
  }

  @override
  Future<NativeLocationStatus> openBackgroundLocationSettings(
    String ownerUserId,
  ) async {
    calls.add('openBackgroundLocationSettings');
    return current;
  }

  @override
  Future<NativeLocationStatus> disableAutomaticLocation(
    String ownerUserId,
  ) async {
    calls.add('disableAutomaticLocation');
    current = disableResult ?? _status(
      permission: current.permission,
      automaticEnabled: false,
      servicesEnabled: current.locationServicesEnabled,
    );
    return current;
  }

  @override
  Future<NativeLocationStatus> start(String ownerUserId) async {
    calls.add('start');
    current = startResult ?? current;
    return current;
  }

  @override
  Future<NativeLocationStatus> pause(String ownerUserId) async {
    calls.add('pause');
    current = pauseResult ?? _status(
      permission: current.permission,
      runtime: NativeLocationRuntime.paused,
      automaticEnabled: current.automaticEnabled,
      servicesEnabled: current.locationServicesEnabled,
      reason: 'paused',
    );
    return current;
  }

  @override
  Future<NativeLocationStatus> stop(String ownerUserId) async {
    calls.add('stop');
    current = stopResult ?? _status(
      permission: current.permission,
      automaticEnabled: current.automaticEnabled,
      servicesEnabled: current.locationServicesEnabled,
    );
    return current;
  }
}

void main() {
  test('initialize is status-only and cannot request permission or start', () async {
    final bridge = _FakeBridge();
    final controller = NativeLocationController(
      bridge: bridge,
      ownerUserId: owner,
    );

    await controller.initialize();

    expect(bridge.calls, <String>['status']);
    expect(controller.privacyGate, NativeLocationPrivacyGate.unknown);
    controller.dispose();
  });

  test('explicit enable requests background stage then starts only when allowed', () async {
    final bridge = _FakeBridge()
      ..current = _status(permission: NativeLocationPermission.foreground)
      ..enableResult = _status(
        permission: NativeLocationPermission.background,
        automaticEnabled: true,
      )
      ..startResult = _status(
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.running,
        automaticEnabled: true,
      );
    final controller = NativeLocationController(
      bridge: bridge,
      ownerUserId: owner,
    );

    await controller.initialize();
    controller.markPrivacyActive();
    await controller.enableAutomaticLocation();

    expect(
      bridge.calls,
      <String>['status', 'enableAutomaticLocation', 'start'],
    );
    expect(controller.status?.runtime, NativeLocationRuntime.running);
    controller.dispose();
  });

  test('running producer is quarantined before privacy verification and can be restored', () async {
    final bridge = _FakeBridge()
      ..current = _status(
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.running,
        automaticEnabled: true,
      )
      ..pauseResult = _status(
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.paused,
        automaticEnabled: true,
        reason: 'paused',
      )
      ..startResult = _status(
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.running,
        automaticEnabled: true,
      );
    final controller = NativeLocationController(
      bridge: bridge,
      ownerUserId: owner,
    );

    await controller.initialize();
    final shouldRestore = await controller.quarantineForPrivacyVerification();

    expect(shouldRestore, isTrue);
    expect(bridge.calls, <String>['status', 'pause']);
    expect(controller.privacyGate, NativeLocationPrivacyGate.unknown);
    expect(controller.status?.runtime, NativeLocationRuntime.paused);

    await controller.resumeVerifiedProducerAfterQuarantine();

    expect(bridge.calls, <String>['status', 'pause', 'start']);
    expect(controller.privacyGate, NativeLocationPrivacyGate.active);
    expect(controller.status?.runtime, NativeLocationRuntime.running);
    controller.dispose();
  });

  test('unknown or paused privacy state blocks native start before the bridge', () async {
    final bridge = _FakeBridge()
      ..current = _status(
        permission: NativeLocationPermission.background,
        automaticEnabled: true,
      );
    final controller = NativeLocationController(
      bridge: bridge,
      ownerUserId: owner,
    );

    await controller.initialize();
    await controller.start();
    expect(bridge.calls, <String>['status']);

    await controller.pauseForPrivacy();
    await controller.start();
    expect(bridge.calls, <String>['status', 'pause']);
    controller.dispose();
  });

  test('privacy resume never requests permission and revoked grant stays stopped', () async {
    final bridge = _FakeBridge()
      ..current = _status(
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.paused,
        automaticEnabled: true,
      )
      ..startResult = _status(
        permission: NativeLocationPermission.foreground,
        automaticEnabled: true,
        reason: 'background_permission_required',
      );
    final controller = NativeLocationController(
      bridge: bridge,
      ownerUserId: owner,
    );

    await controller.initialize();
    await controller.resumeAfterPrivacy();

    expect(bridge.calls, <String>['status', 'start']);
    expect(controller.status?.runtime, NativeLocationRuntime.stopped);
    expect(controller.status?.permission, NativeLocationPermission.foreground);
    controller.dispose();
  });

  test('logout stop queues behind an in-flight permission request', () async {
    final bridge = _FakeBridge()
      ..foregroundCompleter = Completer<NativeLocationStatus>();
    final controller = NativeLocationController(
      bridge: bridge,
      ownerUserId: owner,
    );

    final foreground = controller.requestForegroundPermission();
    final stop = controller.stopForLogout();
    await Future<void>.delayed(Duration.zero);

    expect(bridge.calls, <String>['requestForegroundPermission']);

    bridge.foregroundCompleter!.complete(
      _status(permission: NativeLocationPermission.foreground),
    );
    await foreground;
    await stop;

    expect(
      bridge.calls,
      <String>['requestForegroundPermission', 'stop'],
    );
    controller.dispose();
  });
}
