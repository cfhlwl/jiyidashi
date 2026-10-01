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
  Future<NativeLocationStatus> openLocationServicesSettings(
    String ownerUserId,
  ) async {
    calls.add('openLocationServicesSettings');
    current = NativeLocationStatus(
      supported: true,
      platform: current.platform,
      permission: current.permission,
      runtime: current.runtime,
      automaticEnabled: current.automaticEnabled,
      locationServicesEnabled: true,
      reason: current.reason,
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
  testWidgets('services-off exposes only the exact system-location CTA', (tester) async {
    final bridge = _FakeBridge()
      ..current = const NativeLocationStatus(
        supported: true,
        platform: 'android',
        permission: NativeLocationPermission.background,
        runtime: NativeLocationRuntime.stopped,
        automaticEnabled: true,
        locationServicesEnabled: false,
        reason: 'location_services_disabled',
      );
    final controller = NativeLocationController(
      bridge: bridge,
      ownerUserId: owner,
    );
    await controller.initialize();
    controller.markPrivacyActive();
    var authorityChecks = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: NativeLocationSection(
              controller: controller,
              revalidateAuthority: () async {
                authorityChecks += 1;
                controller.markPrivacyActive();
              },
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(
      find.byKey(const ValueKey('location-open-services-settings')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('location-start')), findsNothing);

    await tester.tap(
      find.byKey(const ValueKey('location-open-services-settings')),
    );
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const ValueKey('location-share-confirm-submit')),
    );
    await tester.pumpAndSettle();

    expect(authorityChecks, 1);
    expect(bridge.calls, <String>['status', 'openLocationServicesSettings']);
    controller.dispose();
  });

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
    var authorityChecks = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: NativeLocationSection(
              controller: controller,
              revalidateAuthority: () async {
                authorityChecks += 1;
                controller.markPrivacyActive();
              },
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    await tester.tap(
      find.byKey(const ValueKey('location-enable-automatic')),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('location-share-confirm-submit')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('location-share-confirm-submit')));
    await tester.pumpAndSettle();

    expect(authorityChecks, 1);
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
    await tester.tap(find.byKey(const ValueKey('location-share-confirm-submit')));
    await tester.pumpAndSettle();

    expect(authorityChecks, 2);
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
    await tester.tap(find.byKey(const ValueKey('location-share-confirm-submit')));
    await tester.pumpAndSettle();

    expect(authorityChecks, 3);
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
    var authorityChecks = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: NativeLocationSection(
              controller: controller,
              revalidateAuthority: () async {
                authorityChecks += 1;
                controller.markPrivacyActive();
              },
            ),
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
    expect(find.byKey(const ValueKey('location-share-confirm-submit')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('location-share-confirm-submit')));
    await tester.pumpAndSettle();
    expect(authorityChecks, 1);
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
    await tester.tap(find.byKey(const ValueKey('location-share-confirm-submit')));
    await tester.pumpAndSettle();

    expect(authorityChecks, 2);
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
