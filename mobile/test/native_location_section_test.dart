import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/native_location_bridge.dart';
import 'package:jiyidashi/native_location_controller.dart';
import 'package:jiyidashi/native_location_section.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';

const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

class _FakeBridge implements NativeLocationBridge {
  _FakeBridge({this.requiresSettings = false});

  final bool requiresSettings;
  final List<String> calls = <String>[];
  NativeLocationStatus current = const NativeLocationStatus(
    supported: true,
    platform: 'test',
    permission: NativeLocationPermission.notDetermined,
    runtime: NativeLocationRuntime.stopped,
    automaticEnabled: false,
    locationServicesEnabled: true,
  );

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
    current = const NativeLocationStatus(
      supported: true,
      platform: 'test',
      permission: NativeLocationPermission.foreground,
      runtime: NativeLocationRuntime.stopped,
      automaticEnabled: false,
      locationServicesEnabled: true,
    );
    return current;
  }

  @override
  Future<NativeLocationStatus> enableAutomaticLocation(String ownerUserId) async {
    calls.add('enableAutomaticLocation');
    current = requiresSettings
        ? const NativeLocationStatus(
            supported: true,
            platform: 'android',
            permission: NativeLocationPermission.foreground,
            runtime: NativeLocationRuntime.stopped,
            automaticEnabled: false,
            locationServicesEnabled: true,
            reason: 'background_settings_required',
          )
        : const NativeLocationStatus(
            supported: true,
            platform: 'test',
            permission: NativeLocationPermission.background,
            runtime: NativeLocationRuntime.stopped,
            automaticEnabled: true,
            locationServicesEnabled: true,
          );
    return current;
  }

  @override
  Future<NativeLocationStatus> start(String ownerUserId) async {
    calls.add('start');
    current = const NativeLocationStatus(
      supported: true,
      platform: 'test',
      permission: NativeLocationPermission.background,
      runtime: NativeLocationRuntime.running,
      automaticEnabled: true,
      locationServicesEnabled: true,
    );
    return current;
  }

  @override
  Future<NativeLocationStatus> pause(String ownerUserId) async {
    calls.add('pause');
    return current;
  }

  @override
  Future<NativeLocationStatus> stop(String ownerUserId) async {
    calls.add('stop');
    return current;
  }

  @override
  Future<NativeLocationStatus> openBackgroundLocationSettings(
    String ownerUserId,
  ) async {
    calls.add('openBackgroundLocationSettings');
    current = const NativeLocationStatus(
      supported: true,
      platform: 'android',
      permission: NativeLocationPermission.background,
      runtime: NativeLocationRuntime.stopped,
      automaticEnabled: true,
      locationServicesEnabled: true,
    );
    return current;
  }

  @override
  Future<NativeLocationStatus> disableAutomaticLocation(
    String ownerUserId,
  ) async {
    calls.add('disableAutomaticLocation');
    return current;
  }
}

void main() {
  testWidgets('Android 11 background grant requires a second explicit settings action', (
    tester,
  ) async {
    final bridge = _FakeBridge(requiresSettings: true)
      ..current = const NativeLocationStatus(
        supported: true,
        platform: 'android',
        permission: NativeLocationPermission.foreground,
        runtime: NativeLocationRuntime.stopped,
        automaticEnabled: false,
        locationServicesEnabled: true,
      );
    final controller = NativeLocationController(
      bridge: bridge,
      ownerUserId: owner,
    );
    await controller.initialize();
    controller.markPrivacyActive();

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: NativeLocationSection(controller: controller),
          ),
        ),
      ),
    );
    await tester.pump();

    await tester.tap(
      find.byKey(const ValueKey('location-enable-automatic')),
    );
    await tester.pumpAndSettle();

    expect(
      bridge.calls,
      <String>['status', 'enableAutomaticLocation'],
    );
    expect(
      find.byKey(const ValueKey('location-open-background-settings')),
      findsOneWidget,
    );
    expect(bridge.calls, isNot(contains('start')));

    await tester.tap(
      find.byKey(const ValueKey('location-open-background-settings')),
    );
    await tester.pumpAndSettle();

    expect(
      bridge.calls,
      <String>[
        'status',
        'enableAutomaticLocation',
        'openBackgroundLocationSettings',
      ],
    );
    expect(find.byKey(const ValueKey('location-start')), findsOneWidget);
    expect(bridge.calls, isNot(contains('start')));

    await tester.tap(find.byKey(const ValueKey('location-start')));
    await tester.pumpAndSettle();

    expect(bridge.calls.last, 'start');
    expect(find.text('自动位置记忆正在运行'), findsOneWidget);
    controller.dispose();
  });

  testWidgets('permission flow is progressive and every request is user-driven', (
    tester,
  ) async {
    final bridge = _FakeBridge();
    final controller = NativeLocationController(
      bridge: bridge,
      ownerUserId: owner,
    );
    await controller.initialize();
    controller.markPrivacyActive();

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: NativeLocationSection(controller: controller),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(bridge.calls, <String>['status']);
    expect(
      find.byKey(const ValueKey('location-request-foreground')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('location-enable-automatic')),
      findsNothing,
    );

    await tester.tap(
      find.byKey(const ValueKey('location-request-foreground')),
    );
    await tester.pumpAndSettle();
    expect(
      bridge.calls,
      <String>['status', 'requestForegroundPermission'],
    );
    expect(
      find.byKey(const ValueKey('location-enable-automatic')),
      findsOneWidget,
    );

    await tester.tap(
      find.byKey(const ValueKey('location-enable-automatic')),
    );
    await tester.pumpAndSettle();

    expect(
      bridge.calls,
      <String>[
        'status',
        'requestForegroundPermission',
        'enableAutomaticLocation',
        'start',
      ],
    );
    expect(find.text('自动位置记忆正在运行'), findsOneWidget);
    controller.dispose();
  });
}
