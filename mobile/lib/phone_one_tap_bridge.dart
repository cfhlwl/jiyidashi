import 'dart:math';

import 'package:flutter/services.dart';

const phoneOneTapCapability = 'PHONE_ONE_TAP';

enum PhoneOneTapState {
  available,
  unavailable,
  cancelled,
  timeout,
  providerError,
  tokenAcquired,
}

/// Provider-neutral result returned by the native adapter.
///
/// [loginToken] is intentionally an in-memory value. It is never included in
/// [toString], persisted state, analytics, or a platform error payload.
class PhoneOneTapResult {
  const PhoneOneTapResult({
    required this.state,
    this.loginToken,
    this.reason,
  });

  const PhoneOneTapResult.available()
      : this(state: PhoneOneTapState.available);

  const PhoneOneTapResult.unavailable([String? reason])
      : this(state: PhoneOneTapState.unavailable, reason: reason);

  const PhoneOneTapResult.cancelled()
      : this(state: PhoneOneTapState.cancelled);

  const PhoneOneTapResult.timeout()
      : this(state: PhoneOneTapState.timeout);

  const PhoneOneTapResult.providerError([String? reason])
      : this(state: PhoneOneTapState.providerError, reason: reason);

  const PhoneOneTapResult.tokenAcquired(String token)
      : this(state: PhoneOneTapState.tokenAcquired, loginToken: token);

  final PhoneOneTapState state;
  final String? loginToken;
  final String? reason;

  bool get isAvailable => state == PhoneOneTapState.available;

  bool get hasLoginToken =>
      state == PhoneOneTapState.tokenAcquired &&
      loginToken != null &&
      loginToken!.trim().isNotEmpty;

  @override
  String toString() => 'PhoneOneTapResult(state: ${state.name}, '
      'reason: ${reason ?? 'none'})';
}

abstract interface class PhoneOneTapBridge {
  Future<PhoneOneTapResult> initialize({
    required bool privacyConsentGranted,
  });

  Future<PhoneOneTapResult> checkAvailability();

  Future<PhoneOneTapResult> preLogin();

  Future<PhoneOneTapResult> requestLoginToken();

  Future<PhoneOneTapResult> cancel();
}

/// Backend surface required by the one-tap coordinator.
///
/// The implementation is the existing [JiYiApiClient]. Keeping this seam
/// small makes response-loss and backend error behavior testable without
/// constructing a provider SDK or persisting a provider token.
abstract interface class PhoneOneTapExchangeClient {
  Future<String> canonicalClientUuid();

  Future<void> exchangePhoneOneTap({
    required String loginToken,
    required String requestId,
    required String deviceId,
    String? clientPlatform,
    String? deviceName,
  });
}

class PhoneOneTapLoginAttempt {
  const PhoneOneTapLoginAttempt({
    required this.requestId,
    required this.loginToken,
    required this.deviceId,
    this.clientPlatform = 'flutter',
    this.deviceName,
  });

  final String requestId;
  final String loginToken;
  final String deviceId;
  final String clientPlatform;
  final String? deviceName;

  /// Deliberately excludes the provider token from diagnostics.
  @override
  String toString() => 'PhoneOneTapLoginAttempt(requestId: $requestId, '
      'deviceId: $deviceId)';
}

class PhoneOneTapLoginCoordinator {
  PhoneOneTapLoginCoordinator({
    required PhoneOneTapBridge bridge,
    required PhoneOneTapExchangeClient exchangeClient,
    this.clientPlatform = 'flutter',
    this.deviceName,
  })  : _bridge = bridge,
        _exchangeClient = exchangeClient;

  final PhoneOneTapBridge _bridge;
  final PhoneOneTapExchangeClient _exchangeClient;
  final String clientPlatform;
  final String? deviceName;

  /// Gets a provider token and creates one in-memory retry envelope.
  ///
  /// A request id is generated only after the native adapter returns a token.
  /// The returned attempt must be retained only for the bounded response-loss
  /// retry window and must never be serialized.
  Future<PhoneOneTapLoginAttempt> requestAttempt() async {
    final tokenResult = await _bridge.requestLoginToken();
    if (!tokenResult.hasLoginToken) {
      throw PhoneOneTapNativeException(tokenResult);
    }
    final token = tokenResult.loginToken!;
    return PhoneOneTapLoginAttempt(
      requestId: _newRequestId(),
      loginToken: token,
      deviceId: await _exchangeClient.canonicalClientUuid(),
      clientPlatform: clientPlatform,
      deviceName: deviceName,
    );
  }

  /// Exchanges the attempt without changing request id or provider token.
  ///
  /// Call this method again after a transport/response-loss failure. The
  /// backend ledger, not Flutter, owns replay and response-loss recovery.
  Future<void> exchange(PhoneOneTapLoginAttempt attempt) {
    return _exchangeClient.exchangePhoneOneTap(
      loginToken: attempt.loginToken,
      requestId: attempt.requestId,
      deviceId: attempt.deviceId,
      clientPlatform: attempt.clientPlatform,
      deviceName: attempt.deviceName,
    );
  }

  static String _newRequestId() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    String hex(int value) => value.toRadixString(16).padLeft(2, '0');
    final encoded = bytes.map(hex).join();
    return '${encoded.substring(0, 8)}-${encoded.substring(8, 12)}-'
        '${encoded.substring(12, 16)}-${encoded.substring(16, 20)}-'
        '${encoded.substring(20)}';
  }
}

class PhoneOneTapNativeException implements Exception {
  PhoneOneTapNativeException(this.result);

  final PhoneOneTapResult result;

  @override
  String toString() => 'PhoneOneTapNativeException(${result.state.name})';
}

class MethodChannelPhoneOneTapBridge implements PhoneOneTapBridge {
  MethodChannelPhoneOneTapBridge({MethodChannel? channel})
      : _channel = channel ?? const MethodChannel('cn.jiyidashi/phone_one_tap');

  final MethodChannel _channel;

  @override
  Future<PhoneOneTapResult> initialize({
    required bool privacyConsentGranted,
  }) async {
    if (!privacyConsentGranted) {
      return const PhoneOneTapResult.unavailable('PRIVACY_NOT_ACCEPTED');
    }
    return _invoke('initialize', <String, Object?>{
      'privacy_consent_granted': true,
    });
  }

  @override
  Future<PhoneOneTapResult> checkAvailability() => _invoke('checkAvailability');

  @override
  Future<PhoneOneTapResult> preLogin() => _invoke('preLogin');

  @override
  Future<PhoneOneTapResult> requestLoginToken() =>
      _invoke('requestLoginToken');

  @override
  Future<PhoneOneTapResult> cancel() => _invoke('cancel');

  Future<PhoneOneTapResult> _invoke(
    String method, [
    Map<String, Object?>? arguments,
  ]) async {
    try {
      final raw = await _channel.invokeMethod<Object?>(method, arguments);
      return _decode(raw);
    } on MissingPluginException {
      return const PhoneOneTapResult.unavailable('NATIVE_UNAVAILABLE');
    } on PlatformException {
      return const PhoneOneTapResult.providerError('NATIVE_ERROR');
    }
  }

  PhoneOneTapResult _decode(Object? raw) {
    if (raw is! Map<Object?, Object?>) {
      return const PhoneOneTapResult.providerError('MALFORMED_RESULT');
    }
    final state = raw['state'];
    if (state is! String) {
      return const PhoneOneTapResult.providerError('MALFORMED_RESULT');
    }
    final reason = raw['reason'];
    final safeReason = reason is String ? reason : null;
    return switch (state) {
      'AVAILABLE' => const PhoneOneTapResult(state: PhoneOneTapState.available),
      'UNAVAILABLE' => PhoneOneTapResult.unavailable(safeReason),
      'CANCELLED' => const PhoneOneTapResult.cancelled(),
      'TIMEOUT' => const PhoneOneTapResult.timeout(),
      'PROVIDER_ERROR' => PhoneOneTapResult.providerError(safeReason),
      'TOKEN_ACQUIRED' => _tokenResult(raw),
      _ => const PhoneOneTapResult.providerError('UNKNOWN_STATE'),
    };
  }

  PhoneOneTapResult _tokenResult(Map<Object?, Object?> raw) {
    final token = raw['login_token'];
    if (token is! String || token.trim().isEmpty) {
      return const PhoneOneTapResult.providerError('MISSING_TOKEN');
    }
    return PhoneOneTapResult.tokenAcquired(token);
  }
}

/// Test seam and local capability model. It never persists or logs its token.
class FakePhoneOneTapBridge implements PhoneOneTapBridge {
  FakePhoneOneTapBridge({
    this.initializeResult = const PhoneOneTapResult.unavailable(
      'FAKE_NOT_CONFIGURED',
    ),
    this.availabilityResult = const PhoneOneTapResult.unavailable(
      'FAKE_NOT_CONFIGURED',
    ),
    this.preLoginResult = const PhoneOneTapResult.available(),
    this.loginResult = const PhoneOneTapResult.cancelled(),
    this.cancelResult = const PhoneOneTapResult.cancelled(),
  });

  PhoneOneTapResult initializeResult;
  PhoneOneTapResult availabilityResult;
  PhoneOneTapResult preLoginResult;
  PhoneOneTapResult loginResult;
  PhoneOneTapResult cancelResult;
  int requestLoginTokenCalls = 0;

  @override
  Future<PhoneOneTapResult> initialize({
    required bool privacyConsentGranted,
  }) async {
    if (!privacyConsentGranted) {
      return const PhoneOneTapResult.unavailable('PRIVACY_NOT_ACCEPTED');
    }
    return initializeResult;
  }

  @override
  Future<PhoneOneTapResult> checkAvailability() async => availabilityResult;

  @override
  Future<PhoneOneTapResult> preLogin() async => preLoginResult;

  @override
  Future<PhoneOneTapResult> requestLoginToken() async {
    requestLoginTokenCalls += 1;
    return loginResult;
  }

  @override
  Future<PhoneOneTapResult> cancel() async => cancelResult;
}
