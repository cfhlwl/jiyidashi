import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/native_location_bridge.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/stage1_app.dart';

const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

class _ZeroQueue extends OfflineQueueStore {
  @override
  Future<int> countAwaitingDelivery(String ownerUserId) async => 0;

  @override
  Future<void> close() async {}
}

class _PrivacyApi extends JiYiApiClient {
  _PrivacyApi({
    required this.paused,
    this.delayedStatus,
    this.throwStatusError = false,
  }) : super(baseUrl: 'https://native-location.invalid/v1') {
    accessToken = 'native-location-token';
    authenticatedUserId = owner;
  }

  final bool paused;
  final Completer<Map<String, dynamic>>? delayedStatus;
  final bool throwStatusError;

  @override
  Future<Map<String, dynamic>> getPrivacyStatus() async {
    if (throwStatusError) {
      throw StateError('privacy status unavailable');
    }
    final delayed = delayedStatus;
    if (delayed != null) return delayed.future;
    return <String, dynamic>{
      'recording_paused': paused,
      'paused_until': paused ? '2026-09-19T16:00:00Z' : null,
    };
  }
}

class _SpyBridge implements NativeLocationBridge {
  final List<String> calls = <String>[];
  late NativeLocationStatus current = _status();

  NativeLocationStatus _status({
    NativeLocationRuntime runtime = NativeLocationRuntime.stopped,
    bool automaticEnabled = true,
  }) {
    return NativeLocationStatus(
      supported: true,
      platform: 'test',
      permission: NativeLocationPermission.background,
      runtime: runtime,
      automaticEnabled: automaticEnabled,
      locationServicesEnabled: true,
    );
  }

  @override
  Future<NativeLocationStatus> status(String ownerUserId) async {
    calls.add('status');
    return current;
  }

  @override
  Future<NativeLocationStatus> requestForegroundPermission(
    String ownerUserId,
  ) async {
    calls.add('requestForegroundPermission');
    return _status();
  }

  @override
  Future<NativeLocationStatus> enableAutomaticLocation(String ownerUserId) async {
    calls.add('enableAutomaticLocation');
    return _status();
  }

  @override
  Future<NativeLocationStatus> openBackgroundLocationSettings(
    String ownerUserId,
  ) async {
    calls.add('openBackgroundLocationSettings');
    return _status();
  }

  @override
  Future<NativeLocationStatus> disableAutomaticLocation(
    String ownerUserId,
  ) async {
    calls.add('disableAutomaticLocation');
    return _status(automaticEnabled: false);
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
    current = _status();
    return current;
  }
}

Future<void> _pumpShell(
  WidgetTester tester, {
  required _PrivacyApi api,
  required _SpyBridge bridge,
  bool resumeAccountDeletion = false,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      home: AppShell(
        api: api,
        offlineQueue: _ZeroQueue(),
        locationBridge: bridge,
        resumeAccountDeletion: resumeAccountDeletion,
        onLogout: () {},
      ),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  testWidgets('login shell only reads native status and never starts tracking', (
    tester,
  ) async {
    final bridge = _SpyBridge();
    await _pumpShell(
      tester,
      api: _PrivacyApi(paused: false),
      bridge: bridge,
    );

    expect(bridge.calls, <String>['status']);
    expect(bridge.calls, isNot(contains('requestForegroundPermission')));
    expect(bridge.calls, isNot(contains('enableAutomaticLocation')));
    expect(bridge.calls, isNot(contains('start')));
  });

  testWidgets('running producer is paused before slow privacy lookup and restored only after active result', (
    tester,
  ) async {
    final privacy = Completer<Map<String, dynamic>>();
    final bridge = _SpyBridge()
      ..current = const NativeLocationStatus(
        supported: true,
        platform: 'test',
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.running,
        automaticEnabled: true,
        locationServicesEnabled: true,
      );

    await _pumpShell(
      tester,
      api: _PrivacyApi(paused: false, delayedStatus: privacy),
      bridge: bridge,
    );

    // The network privacy request is still unresolved, but native production is already
    // quarantined. No location production is allowed during this unknown window.
    expect(bridge.calls, <String>['status', 'pause']);

    privacy.complete(<String, dynamic>{
      'recording_paused': false,
      'paused_until': null,
    });
    await tester.pump(const Duration(milliseconds: 50));

    expect(bridge.calls, <String>['status', 'pause', 'start']);
  });

  testWidgets('iOS relaunch pending restore stays stopped until server privacy is active', (
    tester,
  ) async {
    final privacy = Completer<Map<String, dynamic>>();
    final bridge = _SpyBridge()
      ..current = const NativeLocationStatus(
        supported: true,
        platform: 'ios',
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.stopped,
        automaticEnabled: true,
        locationServicesEnabled: true,
        restorePending: true,
      );

    await _pumpShell(
      tester,
      api: _PrivacyApi(paused: false, delayedStatus: privacy),
      bridge: bridge,
    );

    // Native relaunch only exposes restore_pending. No producer starts while the
    // authoritative server privacy request is unresolved.
    expect(bridge.calls, <String>['status']);

    privacy.complete(<String, dynamic>{
      'recording_paused': false,
      'paused_until': null,
    });
    await tester.pump(const Duration(milliseconds: 50));

    expect(bridge.calls, <String>['status', 'start']);
  });

  testWidgets('iOS relaunch pending restore never starts when server privacy is paused', (
    tester,
  ) async {
    final bridge = _SpyBridge()
      ..current = const NativeLocationStatus(
        supported: true,
        platform: 'ios',
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.stopped,
        automaticEnabled: true,
        locationServicesEnabled: true,
        restorePending: true,
      );

    await _pumpShell(
      tester,
      api: _PrivacyApi(paused: true),
      bridge: bridge,
    );

    expect(bridge.calls, <String>['status', 'pause']);
    expect(bridge.calls, isNot(contains('start')));
  });

  testWidgets('iOS relaunch pending restore never starts when privacy lookup fails', (
    tester,
  ) async {
    final bridge = _SpyBridge()
      ..current = const NativeLocationStatus(
        supported: true,
        platform: 'ios',
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.stopped,
        automaticEnabled: true,
        locationServicesEnabled: true,
        restorePending: true,
      );

    await _pumpShell(
      tester,
      api: _PrivacyApi(paused: false, throwStatusError: true),
      bridge: bridge,
    );

    expect(bridge.calls, <String>['status', 'pause']);
    expect(bridge.calls, isNot(contains('start')));
  });

  testWidgets('authoritative privacy pause stops native production', (tester) async {
    final bridge = _SpyBridge();
    await _pumpShell(
      tester,
      api: _PrivacyApi(paused: true),
      bridge: bridge,
    );

    expect(bridge.calls, <String>['status', 'pause']);
    expect(bridge.calls, isNot(contains('start')));
  });

  testWidgets('account deletion recovery disables account-scoped automatic location', (
    tester,
  ) async {
    final bridge = _SpyBridge();
    await _pumpShell(
      tester,
      api: _PrivacyApi(paused: false),
      bridge: bridge,
      resumeAccountDeletion: true,
    );

    expect(bridge.calls, <String>['disableAutomaticLocation']);
    expect(bridge.calls, isNot(contains('start')));
  });
}
