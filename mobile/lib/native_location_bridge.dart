import 'package:flutter/services.dart';

enum NativeLocationPermission {
  notDetermined,
  foreground,
  background,
  denied,
  restricted,
  unknown,
}

enum NativeLocationRuntime {
  stopped,
  paused,
  running,
}

class NativeLocationStatus {
  const NativeLocationStatus({
    required this.supported,
    required this.platform,
    required this.permission,
    required this.runtime,
    required this.automaticEnabled,
    required this.locationServicesEnabled,
    this.reason,
    this.lastFixAt,
    this.lastAccuracyMeters,
    this.restorePending = false,
  });

  const NativeLocationStatus.unavailable({this.reason})
      : supported = false,
        platform = 'unknown',
        permission = NativeLocationPermission.unknown,
        runtime = NativeLocationRuntime.stopped,
        automaticEnabled = false,
        locationServicesEnabled = false,
        lastFixAt = null,
        lastAccuracyMeters = null,
        restorePending = false;

  final bool supported;
  final String platform;
  final NativeLocationPermission permission;
  final NativeLocationRuntime runtime;
  final bool automaticEnabled;
  final bool locationServicesEnabled;
  final String? reason;
  final DateTime? lastFixAt;
  final double? lastAccuracyMeters;
  final bool restorePending;

  bool get hasForegroundPermission =>
      permission == NativeLocationPermission.foreground ||
      permission == NativeLocationPermission.background;

  bool get hasBackgroundPermission =>
      permission == NativeLocationPermission.background;

  bool get canStart =>
      supported &&
      automaticEnabled &&
      locationServicesEnabled &&
      hasBackgroundPermission;

  static NativeLocationStatus fromPlatform(Object? value) {
    if (value is! Map) {
      return const NativeLocationStatus.unavailable(
        reason: 'invalid_native_status',
      );
    }

    final map = <String, Object?>{};
    value.forEach((key, item) {
      map[key.toString()] = item;
    });

    return NativeLocationStatus(
      supported: map['supported'] == true,
      platform: map['platform']?.toString() ?? 'unknown',
      permission: _parsePermission(map['permission']?.toString()),
      runtime: _parseRuntime(map['runtime']?.toString()),
      automaticEnabled: map['automatic_enabled'] == true,
      locationServicesEnabled: map['location_services_enabled'] == true,
      reason: map['reason']?.toString(),
      lastFixAt: _parseTimestamp(map['last_fix_at']),
      lastAccuracyMeters: _parseDouble(map['last_accuracy_meters']),
      restorePending: map['restore_pending'] == true,
    );
  }

  static NativeLocationPermission _parsePermission(String? value) {
    return switch (value) {
      'not_determined' => NativeLocationPermission.notDetermined,
      'foreground' => NativeLocationPermission.foreground,
      'background' => NativeLocationPermission.background,
      'denied' => NativeLocationPermission.denied,
      'restricted' => NativeLocationPermission.restricted,
      _ => NativeLocationPermission.unknown,
    };
  }

  static NativeLocationRuntime _parseRuntime(String? value) {
    return switch (value) {
      'running' => NativeLocationRuntime.running,
      'paused' => NativeLocationRuntime.paused,
      _ => NativeLocationRuntime.stopped,
    };
  }

  static DateTime? _parseTimestamp(Object? value) {
    if (value == null) return null;
    return DateTime.tryParse(value.toString())?.toUtc();
  }

  static double? _parseDouble(Object? value) {
    if (value is num) return value.toDouble();
    return double.tryParse(value?.toString() ?? '');
  }
}

abstract interface class NativeLocationBridge {
  Future<NativeLocationStatus> status(String ownerUserId);

  Future<NativeLocationStatus> requestForegroundPermission(String ownerUserId);

  Future<NativeLocationStatus> enableAutomaticLocation(String ownerUserId);

  Future<NativeLocationStatus> openBackgroundLocationSettings(
    String ownerUserId,
  );

  Future<NativeLocationStatus> disableAutomaticLocation(String ownerUserId);

  Future<NativeLocationStatus> start(String ownerUserId);

  Future<NativeLocationStatus> pause(String ownerUserId);

  Future<NativeLocationStatus> stop(String ownerUserId);
}

/// Native status reads are deliberately separate from permission and start commands.
/// Constructing this bridge, logging in, or opening onboarding can never request location
/// permission or start production; only explicit command methods can cross that boundary.
class MethodChannelNativeLocationBridge implements NativeLocationBridge {
  MethodChannelNativeLocationBridge({
    MethodChannel channel = const MethodChannel(
      'cn.jiyidashi/native_location',
    ),
  }) : _channel = channel;

  final MethodChannel _channel;

  Map<String, Object?> _arguments(String ownerUserId) {
    final owner = ownerUserId.trim();
    if (owner.isEmpty) {
      throw ArgumentError.value(
        ownerUserId,
        'ownerUserId',
        'authenticated user id is required',
      );
    }
    return <String, Object?>{'owner_user_id': owner};
  }

  Future<NativeLocationStatus> _invoke(
    String method,
    String ownerUserId,
  ) async {
    final result = await _channel.invokeMethod<Object?>(
      method,
      _arguments(ownerUserId),
    );
    return NativeLocationStatus.fromPlatform(result);
  }

  @override
  Future<NativeLocationStatus> status(String ownerUserId) =>
      _invoke('status', ownerUserId);

  @override
  Future<NativeLocationStatus> requestForegroundPermission(
    String ownerUserId,
  ) =>
      _invoke('requestForegroundPermission', ownerUserId);

  @override
  Future<NativeLocationStatus> enableAutomaticLocation(String ownerUserId) =>
      _invoke('enableAutomaticLocation', ownerUserId);

  @override
  Future<NativeLocationStatus> openBackgroundLocationSettings(
    String ownerUserId,
  ) =>
      _invoke('openBackgroundLocationSettings', ownerUserId);

  @override
  Future<NativeLocationStatus> disableAutomaticLocation(String ownerUserId) =>
      _invoke('disableAutomaticLocation', ownerUserId);

  @override
  Future<NativeLocationStatus> start(String ownerUserId) =>
      _invoke('start', ownerUserId);

  @override
  Future<NativeLocationStatus> pause(String ownerUserId) =>
      _invoke('pause', ownerUserId);

  @override
  Future<NativeLocationStatus> stop(String ownerUserId) =>
      _invoke('stop', ownerUserId);
}
