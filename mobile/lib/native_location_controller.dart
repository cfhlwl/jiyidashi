import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'native_location_bridge.dart';

enum NativeLocationPrivacyGate {
  unknown,
  active,
  paused,
}

class NativeLocationController extends ChangeNotifier {
  NativeLocationController({
    required this.bridge,
    required String ownerUserId,
  }) : ownerUserId = ownerUserId.trim() {
    if (this.ownerUserId.isEmpty) {
      throw ArgumentError.value(
        ownerUserId,
        'ownerUserId',
        'authenticated user id is required',
      );
    }
  }

  final NativeLocationBridge bridge;
  final String ownerUserId;

  NativeLocationStatus? _status;
  bool _busy = false;
  bool _disposed = false;
  String? _error;
  NativeLocationPrivacyGate _privacyGate = NativeLocationPrivacyGate.unknown;
  Future<void> _operationTail = Future<void>.value();

  NativeLocationStatus? get status => _status;
  bool get busy => _busy;
  String? get error => _error;
  NativeLocationPrivacyGate get privacyGate => _privacyGate;
  bool get privacyAllowsProduction =>
      _privacyGate == NativeLocationPrivacyGate.active;

  /// Initialization is read-only by design. This is the hard product boundary that
  /// prevents app launch/login/onboarding from becoming an implicit permission wall
  /// or hidden location start.
  Future<void> initialize() => refresh();

  Future<void> refresh() async {
    await _run(() => bridge.status(ownerUserId));
  }

  Future<void> requestForegroundPermission() async {
    await _run(() => bridge.requestForegroundPermission(ownerUserId));
  }

  /// The second permission stage only happens behind this explicit user action.
  /// Native code still fails closed if foreground permission is missing or if the
  /// background/Always grant is denied.
  Future<void> enableAutomaticLocation() async {
    if (!privacyAllowsProduction) {
      _error = '当前隐私状态不允许启动自动位置记忆';
      _notify();
      return;
    }
    await _run(() => bridge.enableAutomaticLocation(ownerUserId));
    final next = _status;
    if (_disposed || next == null || !next.canStart) return;
    await _run(() => bridge.start(ownerUserId));
  }

  Future<void> openBackgroundLocationSettings() async {
    if (!privacyAllowsProduction) {
      _error = '当前隐私状态不允许启用自动位置记忆';
      _notify();
      return;
    }
    await _run(() => bridge.openBackgroundLocationSettings(ownerUserId));
  }

  Future<void> start() async {
    if (!privacyAllowsProduction) {
      _error = '当前隐私状态不允许启动自动位置记忆';
      _notify();
      return;
    }
    await _run(() => bridge.start(ownerUserId));
  }

  Future<void> disableAutomaticLocation() async {
    await _run(() => bridge.disableAutomaticLocation(ownerUserId));
  }

  void markPrivacyActive() {
    if (_disposed) return;
    // Reading active privacy status never starts native production. A stopped producer
    // stays stopped until the user explicitly enables/starts it.
    _privacyGate = NativeLocationPrivacyGate.active;
    _notify();
  }

  /// Quarantines an already-running native producer while authoritative server privacy
  /// is still unknown. Returns true only when this session is allowed to restore the
  /// previous producer after the server explicitly confirms privacy is active.
  Future<bool> quarantineForPrivacyVerification() async {
    if (_disposed) return false;
    _privacyGate = NativeLocationPrivacyGate.unknown;
    _notify();

    final current = _status;
    final shouldRestore = current?.canStart == true &&
        (current?.runtime == NativeLocationRuntime.running ||
            current?.restorePending == true);
    if (current?.runtime == NativeLocationRuntime.running) {
      await _run(() => bridge.pause(ownerUserId), exposeError: false);
    }
    return shouldRestore && !_disposed;
  }

  Future<void> resumeVerifiedProducerAfterQuarantine() async {
    if (_disposed) return;
    _privacyGate = NativeLocationPrivacyGate.active;
    _notify();
    final current = _status;
    if (current == null || !current.canStart) return;
    // This is a restore of a producer that was already running before privacy verification.
    // It never calls either permission method; revoked permission still fails closed natively.
    await _run(() => bridge.start(ownerUserId), exposeError: false);
  }

  Future<void> pauseForPrivacy() async {
    _privacyGate = NativeLocationPrivacyGate.paused;
    _notify();
    await _run(() => bridge.pause(ownerUserId));
  }

  /// Privacy resume may restart an already-enabled native producer, but it never calls
  /// either permission method. If permission was revoked while paused, native start
  /// returns a stopped/fail-closed status and the UI asks the user to act explicitly.
  Future<void> resumeAfterPrivacy() async {
    _privacyGate = NativeLocationPrivacyGate.active;
    _notify();
    await _run(() => bridge.start(ownerUserId));
  }

  Future<void> privacyStatusUnknown() async {
    // Unknown server privacy state is not permission to keep producing location.
    _privacyGate = NativeLocationPrivacyGate.unknown;
    _notify();
    await _run(() => bridge.pause(ownerUserId));
  }

  Future<void> stopForLogout() async {
    await _run(() => bridge.stop(ownerUserId), exposeError: false);
  }

  Future<void> disableForAccountDeletion() async {
    await _run(
      () => bridge.disableAutomaticLocation(ownerUserId),
      exposeError: false,
    );
  }

  Future<void> _run(
    Future<NativeLocationStatus> Function() operation, {
    bool exposeError = true,
  }) {
    final queued = _operationTail.then((_) async {
      if (_disposed) return;
      _busy = true;
      _error = null;
      _notify();

      try {
        final next = await operation();
        if (_disposed) return;
        // Unknown native payloads parse to stopped/unsupported, never to running.
        _status = next;
      } on MissingPluginException {
        if (_disposed) return;
        _status = const NativeLocationStatus.unavailable(
          reason: 'native_bridge_unavailable',
        );
        if (exposeError) _error = '当前设备暂不支持自动位置记忆';
      } on PlatformException catch (exc) {
        if (_disposed) return;
        _status = const NativeLocationStatus.unavailable(
          reason: 'native_bridge_error',
        );
        if (exposeError) {
          _error = exc.message ?? '无法读取系统定位状态';
        }
      } catch (_) {
        if (_disposed) return;
        _status = const NativeLocationStatus.unavailable(
          reason: 'native_bridge_error',
        );
        if (exposeError) _error = '无法读取系统定位状态';
      } finally {
        if (!_disposed) {
          _busy = false;
          _notify();
        }
      }
    });
    // Privacy pause/logout/account deletion must queue behind an in-flight permission
    // operation instead of being dropped. Every operation handles its own errors, so the
    // tail remains usable for later fail-closed stop/disable commands.
    _operationTail = queued;
    return queued;
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
