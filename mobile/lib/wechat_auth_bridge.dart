import 'dart:math';

import 'package:flutter/services.dart';

const wechatCapability = 'WECHAT';

enum WechatAuthState {
  available,
  unavailable,
  cancelled,
  timeout,
  providerError,
  credentialAcquired,
}

/// Provider-neutral native result. The transient credential is intentionally
/// excluded from diagnostics and must never be persisted or logged.
class WechatAuthResult {
  const WechatAuthResult({required this.state, this.credential, this.reason});

  const WechatAuthResult.available() : this(state: WechatAuthState.available);
  const WechatAuthResult.unavailable([String? reason])
    : this(state: WechatAuthState.unavailable, reason: reason);
  const WechatAuthResult.cancelled() : this(state: WechatAuthState.cancelled);
  const WechatAuthResult.timeout() : this(state: WechatAuthState.timeout);
  const WechatAuthResult.providerError([String? reason])
    : this(state: WechatAuthState.providerError, reason: reason);
  const WechatAuthResult.credentialAcquired(String value)
    : this(state: WechatAuthState.credentialAcquired, credential: value);

  final WechatAuthState state;
  final String? credential;
  final String? reason;

  bool get isAvailable => state == WechatAuthState.available;
  bool get hasCredential =>
      state == WechatAuthState.credentialAcquired &&
      credential != null &&
      credential!.trim().isNotEmpty;

  @override
  String toString() =>
      'WechatAuthResult(state: ${state.name}, '
      'reason: ${reason ?? 'none'})';
}

abstract interface class WechatAuthGateway {
  Future<WechatAuthResult> initialize({required bool privacyConsentGranted});
  Future<WechatAuthResult> checkAvailability();
  Future<WechatAuthResult> requestCredential();
  Future<WechatAuthResult> cancel();
  Future<WechatAuthResult> revokePrivacy();
}

abstract interface class WechatExchangeClient {
  Future<String> canonicalClientUuid();

  Future<void> exchangeWechatCredential({
    required String credential,
    required String requestId,
    required String deviceId,
    String? clientPlatform,
    String? deviceName,
  });
}

class WechatLoginAttempt {
  const WechatLoginAttempt({
    required this.requestId,
    required this.credential,
    required this.deviceId,
  });

  final String requestId;
  final String credential;
  final String deviceId;

  @override
  String toString() =>
      'WechatLoginAttempt(requestId: $requestId, '
      'deviceId: $deviceId)';
}

class WechatLoginCoordinator {
  WechatLoginCoordinator({
    required WechatAuthGateway gateway,
    required WechatExchangeClient exchangeClient,
  }) : _gateway = gateway,
       _exchangeClient = exchangeClient;

  final WechatAuthGateway _gateway;
  final WechatExchangeClient _exchangeClient;

  Future<WechatLoginAttempt> requestAttempt() async {
    final result = await _gateway.requestCredential();
    if (!result.hasCredential) throw WechatAuthNativeException(result);
    return WechatLoginAttempt(
      requestId: _newRequestId(),
      credential: result.credential!,
      deviceId: await _exchangeClient.canonicalClientUuid(),
    );
  }

  Future<void> exchange(WechatLoginAttempt attempt) =>
      _exchangeClient.exchangeWechatCredential(
        credential: attempt.credential,
        requestId: attempt.requestId,
        deviceId: attempt.deviceId,
        clientPlatform: 'flutter',
      );

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

class WechatAuthNativeException implements Exception {
  WechatAuthNativeException(this.result);
  final WechatAuthResult result;

  @override
  String toString() => 'WechatAuthNativeException(${result.state.name})';
}

class MethodChannelWechatAuthGateway implements WechatAuthGateway {
  MethodChannelWechatAuthGateway({MethodChannel? channel})
    : _channel = channel ?? MethodChannel('cn.jiyidashi/wechat_auth');

  final MethodChannel _channel;

  @override
  Future<WechatAuthResult> initialize({required bool privacyConsentGranted}) =>
      _invoke('initialize', {'privacy_consent_granted': privacyConsentGranted});

  @override
  Future<WechatAuthResult> revokePrivacy() =>
      _invoke('revokePrivacy');

  @override
  Future<WechatAuthResult> checkAvailability() => _invoke('checkAvailability');

  @override
  Future<WechatAuthResult> requestCredential() => _invoke('requestCredential');

  @override
  Future<WechatAuthResult> cancel() => _invoke('cancel');

  Future<WechatAuthResult> _invoke(
    String method, [
    Map<String, Object?>? args,
  ]) async {
    try {
      return _decode(await _channel.invokeMethod<Object?>(method, args));
    } on MissingPluginException {
      return const WechatAuthResult.unavailable('NATIVE_UNAVAILABLE');
    } on PlatformException {
      return const WechatAuthResult.providerError('NATIVE_ERROR');
    }
  }

  WechatAuthResult _decode(Object? raw) {
    if (raw is! Map<Object?, Object?> || raw['state'] is! String) {
      return const WechatAuthResult.providerError('MALFORMED_RESULT');
    }
    final state = raw['state'] as String;
    final reason = raw['reason'] is String ? raw['reason'] as String : null;
    return switch (state) {
      'AVAILABLE' => const WechatAuthResult.available(),
      'UNAVAILABLE' => WechatAuthResult.unavailable(reason),
      'CANCELLED' => const WechatAuthResult.cancelled(),
      'TIMEOUT' => const WechatAuthResult.timeout(),
      'PROVIDER_ERROR' => WechatAuthResult.providerError(reason),
      'CREDENTIAL_ACQUIRED' => _credential(raw),
      _ => const WechatAuthResult.providerError('UNKNOWN_STATE'),
    };
  }

  WechatAuthResult _credential(Map<Object?, Object?> raw) {
    final value = raw['credential'];
    if (value is! String || value.trim().isEmpty) {
      return const WechatAuthResult.providerError('MISSING_CREDENTIAL');
    }
    return WechatAuthResult.credentialAcquired(value);
  }
}

class FakeWechatAuthGateway implements WechatAuthGateway {
  FakeWechatAuthGateway({
    this.initializeResult = const WechatAuthResult.available(),
    this.availabilityResult = const WechatAuthResult.available(),
    this.credentialResult = const WechatAuthResult.credentialAcquired(
      'test-credential',
    ),
  });

  WechatAuthResult initializeResult;
  WechatAuthResult availabilityResult;
  WechatAuthResult credentialResult;
  int initializeCalls = 0;
  int checkAvailabilityCalls = 0;
  int requestCredentialCalls = 0;
  int cancelCalls = 0;
  int revokePrivacyCalls = 0;

  @override
  Future<WechatAuthResult> initialize({
    required bool privacyConsentGranted,
  }) async {
    initializeCalls += 1;
    return privacyConsentGranted ? initializeResult : await revokePrivacy();
  }

  @override
  Future<WechatAuthResult> checkAvailability() async {
    checkAvailabilityCalls += 1;
    return availabilityResult;
  }

  @override
  Future<WechatAuthResult> requestCredential() async {
    requestCredentialCalls += 1;
    return credentialResult;
  }

  @override
  Future<WechatAuthResult> cancel() async {
    cancelCalls += 1;
    return const WechatAuthResult.cancelled();
  }

  @override
  Future<WechatAuthResult> revokePrivacy() async {
    revokePrivacyCalls += 1;
    return const WechatAuthResult.unavailable('PRIVACY_REVOKED');
  }
}
