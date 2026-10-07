import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api_client.dart';

enum NotificationPermissionState {
  notDetermined,
  authorized,
  provisional,
  denied,
  unavailable,
}

enum NotificationRegistrationState {
  idle,
  registrationPending,
  registered,
  denied,
  providerUnavailable,
  serverUnavailable,
}

enum NotificationDestination {
  home,
  reminder,
  memory,
  appUpdate,
  family,
  export,
}

class PushRouteIntent {
  const PushRouteIntent({
    required this.destination,
    this.resourceId,
  });

  final NotificationDestination destination;
  final String? resourceId;

  static final RegExp _uuid = RegExp(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-'
    r'[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
  );

  static PushRouteIntent? parse(Object? raw) {
    if (raw is! Map) return null;
    final version = raw['version'];
    if (version != 1) return null;

    final destination = switch (raw['destination']) {
      'HOME' => NotificationDestination.home,
      'REMINDER' => NotificationDestination.reminder,
      'MEMORY' => NotificationDestination.memory,
      'APP_UPDATE' => NotificationDestination.appUpdate,
      'FAMILY' => NotificationDestination.family,
      'EXPORT' => NotificationDestination.export,
      _ => NotificationDestination.home,
    };
    final resourceRaw = raw['resource_id'];
    final resource = resourceRaw?.toString();
    if (resource != null && !_uuid.hasMatch(resource)) {
      return const PushRouteIntent(destination: NotificationDestination.home);
    }
    if (destination == NotificationDestination.memory && resource == null) {
      return const PushRouteIntent(destination: NotificationDestination.home);
    }
    return PushRouteIntent(destination: destination, resourceId: resource);
  }
}

class NativePushStatus {
  const NativePushStatus({
    required this.supported,
    required this.platform,
    required this.permission,
    this.provider,
    this.token,
    this.appVersion,
    this.osVersion,
  });

  const NativePushStatus.unavailable()
      : supported = false,
        platform = 'UNKNOWN',
        permission = NotificationPermissionState.unavailable,
        provider = null,
        token = null,
        appVersion = null,
        osVersion = null;

  final bool supported;
  final String platform;
  final NotificationPermissionState permission;
  final String? provider;
  final String? token;
  final String? appVersion;
  final String? osVersion;

  bool get mayRegister =>
      supported &&
      (permission == NotificationPermissionState.authorized ||
          permission == NotificationPermissionState.provisional);

  factory NativePushStatus.fromPlatform(Object? raw) {
    if (raw is! Map) return const NativePushStatus.unavailable();
    final platform = raw['platform']?.toString().toUpperCase();
    final permission = switch (raw['permission']?.toString()) {
      'notDetermined' => NotificationPermissionState.notDetermined,
      'authorized' => NotificationPermissionState.authorized,
      'provisional' => NotificationPermissionState.provisional,
      'denied' => NotificationPermissionState.denied,
      _ => NotificationPermissionState.unavailable,
    };
    final provider = raw['provider']?.toString().toUpperCase();
    final token = raw['token']?.toString();
    return NativePushStatus(
      supported: raw['supported'] == true,
      platform: platform == 'IOS' || platform == 'ANDROID'
          ? platform!
          : 'UNKNOWN',
      permission: permission,
      provider: provider == null || provider.isEmpty ? null : provider,
      token: token == null || token.trim().isEmpty ? null : token.trim(),
      appVersion: raw['app_version']?.toString(),
      osVersion: raw['os_version']?.toString(),
    );
  }
}

class NativePushEvent {
  const NativePushEvent({
    required this.kind,
    this.status,
    this.payload,
    this.eventId,
  });

  final String kind;
  final NativePushStatus? status;
  final Object? payload;
  final String? eventId;
}

typedef NativePushEventHandler = Future<void> Function(NativePushEvent event);

abstract interface class NativeNotificationBridge {
  Future<void> attach(NativePushEventHandler handler);
  Future<NativePushStatus> status();
  Future<NativePushStatus> requestPermission();
  Future<NativePushStatus> registerForPush();
  Future<void> unregisterFromPush();
  Future<void> close();
}

class MethodChannelNativeNotificationBridge implements NativeNotificationBridge {
  MethodChannelNativeNotificationBridge({
    MethodChannel? channel,
  }) : _channel = channel ?? const MethodChannel('cn.jiyidashi/notifications');

  final MethodChannel _channel;
  NativePushEventHandler? _handler;

  @override
  Future<void> attach(NativePushEventHandler handler) async {
    _handler = handler;
    _channel.setMethodCallHandler((call) async {
      final callback = _handler;
      if (callback == null) return;
      final arguments = call.arguments;
      if (call.method == 'token' || call.method == 'permission') {
        await callback(
          NativePushEvent(
            kind: call.method,
            status: NativePushStatus.fromPlatform(arguments),
          ),
        );
        return;
      }
      if (call.method == 'notification' || call.method == 'tap') {
        Object? payload;
        String? eventId;
        if (arguments is Map) {
          payload = arguments['payload'];
          eventId = arguments['event_id']?.toString();
        }
        await callback(
          NativePushEvent(
            kind: call.method,
            payload: payload,
            eventId: eventId,
          ),
        );
      }
    });
    try {
      await _channel.invokeMethod<void>('ready');
    } on MissingPluginException {
      // Unit/widget tests and unsupported platforms have no native push bridge.
    } on PlatformException {
      // A native bridge that cannot become ready remains provider-unavailable.
    }
  }

  @override
  Future<NativePushStatus> status() async {
    final raw = await _channel.invokeMethod<Object?>('status');
    return NativePushStatus.fromPlatform(raw);
  }

  @override
  Future<NativePushStatus> requestPermission() async {
    final raw = await _channel.invokeMethod<Object?>('requestPermission');
    return NativePushStatus.fromPlatform(raw);
  }

  @override
  Future<NativePushStatus> registerForPush() async {
    final raw = await _channel.invokeMethod<Object?>('registerForPush');
    return NativePushStatus.fromPlatform(raw);
  }

  @override
  Future<void> unregisterFromPush() {
    return _channel.invokeMethod<void>('unregisterFromPush');
  }

  @override
  Future<void> close() async {
    _handler = null;
    _channel.setMethodCallHandler(null);
  }
}

class StoredPushToken {
  const StoredPushToken({
    required this.platform,
    required this.provider,
    required this.token,
    this.registeredOwner,
    this.retirePending = false,
  });

  final String platform;
  final String provider;
  final String token;
  final String? registeredOwner;
  final bool retirePending;

  Map<String, Object?> toJson() => <String, Object?>{
        'platform': platform,
        'provider': provider,
        'token': token,
        'registered_owner': registeredOwner,
        'retire_pending': retirePending,
      };

  factory StoredPushToken.fromJson(Map<String, dynamic> data) {
    final platform = data['platform'];
    final provider = data['provider'];
    final token = data['token'];
    if ((platform != 'IOS' && platform != 'ANDROID') ||
        (provider != 'APNS' && provider != 'FCM' && provider != 'HMS') ||
        token is! String ||
        token.trim().isEmpty) {
      throw const FormatException('invalid push token state');
    }
    final owner = data['registered_owner'];
    return StoredPushToken(
      platform: platform as String,
      provider: provider as String,
      token: token.trim(),
      registeredOwner:
          owner is String && owner.trim().isNotEmpty ? owner.trim() : null,
      retirePending: data['retire_pending'] == true,
    );
  }

  StoredPushToken copyWith({
    String? registeredOwner,
    bool clearRegisteredOwner = false,
    bool? retirePending,
  }) {
    return StoredPushToken(
      platform: platform,
      provider: provider,
      token: token,
      registeredOwner:
          clearRegisteredOwner ? null : (registeredOwner ?? this.registeredOwner),
      retirePending: retirePending ?? this.retirePending,
    );
  }
}

abstract interface class NotificationTokenStore {
  Future<StoredPushToken?> read();
  Future<void> write(StoredPushToken token);
  Future<void> clear();
}

class SecureNotificationTokenStore implements NotificationTokenStore {
  SecureNotificationTokenStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  static const _key = 'jiyi.push.v1.token';
  final FlutterSecureStorage _storage;

  @override
  Future<StoredPushToken?> read() async {
    final raw = await _storage.read(key: _key);
    if (raw == null || raw.trim().isEmpty) return null;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) throw const FormatException();
      return StoredPushToken.fromJson(decoded);
    } on FormatException {
      await clear();
      return null;
    }
  }

  @override
  Future<void> write(StoredPushToken token) {
    return _storage.write(key: _key, value: jsonEncode(token.toJson()));
  }

  @override
  Future<void> clear() => _storage.delete(key: _key);
}

class MemoryNotificationTokenStore implements NotificationTokenStore {
  StoredPushToken? token;

  @override
  Future<StoredPushToken?> read() async => token;

  @override
  Future<void> write(StoredPushToken value) async {
    token = value;
  }

  @override
  Future<void> clear() async {
    token = null;
  }
}

class NotificationClientService extends ChangeNotifier {
  NotificationClientService({
    required this.api,
    NativeNotificationBridge? nativeBridge,
    NotificationTokenStore? tokenStore,
  })  : nativeBridge =
            nativeBridge ?? MethodChannelNativeNotificationBridge(),
        tokenStore = tokenStore ?? SecureNotificationTokenStore();

  final JiYiApiClient api;
  final NativeNotificationBridge nativeBridge;
  final NotificationTokenStore tokenStore;

  NotificationPermissionState permission =
      NotificationPermissionState.notDetermined;
  NotificationRegistrationState registration =
      NotificationRegistrationState.idle;
  String? provider;
  String? platform;

  StoredPushToken? _token;
  Future<void> _tail = Future<void>.value();
  Future<void> Function(PushRouteIntent intent)? _routeHandler;
  final List<PushRouteIntent> _pendingRoutes = <PushRouteIntent>[];
  String? _lastTapKey;
  DateTime? _lastTapAt;
  bool _initialized = false;
  bool _closed = false;

  void _publishState() {
    if (!_closed) notifyListeners();
  }

  Future<void> initialize() async {
    if (_initialized) return;
    _initialized = true;
    try {
      await nativeBridge.attach(_handleNativeEvent);
    } on MissingPluginException {
      permission = NotificationPermissionState.unavailable;
      registration = NotificationRegistrationState.providerUnavailable;
      _publishState();
      return;
    } on PlatformException {
      permission = NotificationPermissionState.unavailable;
      registration = NotificationRegistrationState.providerUnavailable;
      _publishState();
      return;
    }
    _token = await tokenStore.read();
    if (_token?.retirePending == true) {
      await _retryPendingRetirement();
    }
    NativePushStatus status;
    try {
      status = await nativeBridge.status();
    } on MissingPluginException {
      status = const NativePushStatus.unavailable();
    } on PlatformException {
      status = const NativePushStatus.unavailable();
    }
    await _consumeStatus(status, synchronize: true);
    _publishState();
  }

  Future<void> requestPermissionAndRegister() async {
    registration = NotificationRegistrationState.registrationPending;
    _publishState();
    NativePushStatus next;
    try {
      next = await nativeBridge.requestPermission();
    } on MissingPluginException {
      registration = NotificationRegistrationState.providerUnavailable;
      _publishState();
      return;
    } on PlatformException {
      registration = NotificationRegistrationState.providerUnavailable;
      return;
    }
    permission = next.permission;
    if (!next.mayRegister) {
      registration = next.permission == NotificationPermissionState.denied
          ? NotificationRegistrationState.denied
          : NotificationRegistrationState.providerUnavailable;
      await _retireServerBindingIfPossible();
      _publishState();
      return;
    }

    try {
      next = await nativeBridge.registerForPush();
    } on MissingPluginException {
      registration = NotificationRegistrationState.providerUnavailable;
      return;
    } on PlatformException {
      registration = NotificationRegistrationState.providerUnavailable;
      return;
    }
    await _consumeStatus(next, synchronize: false);
    if (next.token != null) {
      await _synchronizeCurrentOwner();
    } else {
      registration = NotificationRegistrationState.registrationPending;
    }
    _publishState();
  }

  Future<void> onAuthenticated() => _serial(_ensureAuthorizedOwnerRegistration);

  Future<void> onAppResumed() => _serial(() async {
        NativePushStatus current;
        try {
          current = await nativeBridge.status();
        } on Object {
          registration = NotificationRegistrationState.providerUnavailable;
          return;
        }
        await _consumeStatus(current, synchronize: false);
        await _ensureAuthorizedOwnerRegistration();
      });

  Future<void> onTerminalAuthLoss() => _serial(() async {
        await _retireNativeToken();
        registration = NotificationRegistrationState.idle;
      });

  Future<void> prepareForLogout() => _serial(() async {
        final owner = api.authenticatedUserId;
        final version = api.sessionVersion;
        final clientUuid = await api.canonicalClientUuid();
        PushSessionBinding? binding;
        if (owner != null && owner.trim().isNotEmpty) {
          try {
            binding = api.capturePushSession();
          } on ApiException {
            binding = null;
          }
        }

        if (binding != null) {
          try {
            await api.unregisterPushDevice(
              clientUuid: clientUuid,
              session: binding,
            );
            if (api.sessionVersion == version &&
                api.authenticatedUserId == owner) {
              _token = _token?.copyWith(clearRegisteredOwner: true);
              if (_token != null) await tokenStore.write(_token!);
            }
          } on Object {
            // Server auth logout also fences the session's canonical Device binding
            // when reachable. Native token retirement below is the offline fallback.
          }
        }
        await _retireNativeToken();
        registration = NotificationRegistrationState.idle;
      });

  void setRouteHandler(
    Future<void> Function(PushRouteIntent intent)? handler,
  ) {
    _routeHandler = handler;
    if (handler != null) {
      unawaited(_drainPendingRoutes());
    }
  }

  Future<void> close() async {
    if (_closed) return;
    _routeHandler = null;
    _pendingRoutes.clear();
    await nativeBridge.close();
    _closed = true;
    dispose();
  }

  Future<void> _serial(Future<void> Function() operation) {
    final previous = _tail.then<void>(
      (_) {},
      onError: (Object _, StackTrace __) {},
    );
    final current = previous.then((_) => operation());
    _tail = current.then<void>(
      (_) {},
      onError: (Object _, StackTrace __) {},
    );
    return current.whenComplete(_publishState);
  }

  Future<void> _handleNativeEvent(NativePushEvent event) async {
    if (event.kind == 'token' || event.kind == 'permission') {
      final status = event.status;
      if (status != null) {
        await _serial(() => _consumeStatus(status, synchronize: true));
      }
      return;
    }
    if (event.kind == 'tap') {
      final intent = PushRouteIntent.parse(event.payload);
      if (intent == null) return;
      final key = event.eventId?.trim().isNotEmpty == true
          ? event.eventId!.trim()
          : '${intent.destination.name}:${intent.resourceId ?? '-'}';
      final now = DateTime.now().toUtc();
      if (_lastTapKey == key &&
          _lastTapAt != null &&
          now.difference(_lastTapAt!) < const Duration(seconds: 3)) {
        return;
      }
      _lastTapKey = key;
      _lastTapAt = now;
      await _publishRoute(intent);
    }
  }

  Future<void> _consumeStatus(
    NativePushStatus status, {
    required bool synchronize,
  }) async {
    permission = status.permission;
    platform = status.platform == 'UNKNOWN' ? platform : status.platform;
    provider = status.provider ?? provider;

    if (status.permission == NotificationPermissionState.denied) {
      registration = NotificationRegistrationState.denied;
      await _retireServerBindingIfPossible();
      return;
    }

    final token = status.token;
    final statusProvider = status.provider;
    if (token != null &&
        statusProvider != null &&
        (status.platform == 'IOS' || status.platform == 'ANDROID')) {
      final previous = _token;
      final same = previous?.token == token &&
          previous?.provider == statusProvider &&
          previous?.platform == status.platform;
      _token = StoredPushToken(
        platform: status.platform,
        provider: statusProvider,
        token: token,
        registeredOwner: same ? previous?.registeredOwner : null,
      );
      await tokenStore.write(_token!);
    }
    if (synchronize) await _synchronizeCurrentOwner();
  }

  Future<void> _ensureAuthorizedOwnerRegistration() async {
    if (api.authenticatedUserId == null) return;
    if (permission != NotificationPermissionState.authorized &&
        permission != NotificationPermissionState.provisional) {
      return;
    }
    if (_token?.retirePending == true) {
      await _retryPendingRetirement();
      if (_token?.retirePending == true) {
        registration = NotificationRegistrationState.providerUnavailable;
        return;
      }
    }
    try {
      final native = await nativeBridge.registerForPush();
      await _consumeStatus(native, synchronize: false);
      if (native.token == null) {
        registration = NotificationRegistrationState.registrationPending;
        return;
      }
    } on Object {
      registration = NotificationRegistrationState.providerUnavailable;
      return;
    }
    await _synchronizeCurrentOwner();
  }

  Future<void> _synchronizeCurrentOwner() async {
    final token = _token;
    final owner = api.authenticatedUserId;
    if (token == null || owner == null || owner.trim().isEmpty) return;
    if (permission != NotificationPermissionState.authorized &&
        permission != NotificationPermissionState.provisional) {
      return;
    }

    final version = api.sessionVersion;
    late final PushSessionBinding binding;
    try {
      binding = api.capturePushSession();
    } on ApiException {
      return;
    }
    if (binding.ownerUserId != owner) return;

    registration = NotificationRegistrationState.registrationPending;
    try {
      final clientUuid = await api.canonicalClientUuid();
      if (api.sessionVersion != version ||
          api.authenticatedUserId != owner) {
        return;
      }
      await api.registerPushDevice(
        clientUuid: clientUuid,
        platform: token.platform,
        provider: token.provider,
        pushToken: token.token,
        session: binding,
      );
      api.assertPushSessionCurrent(binding);
      _token = token.copyWith(
        registeredOwner: owner,
        retirePending: false,
      );
      await tokenStore.write(_token!);
      registration = NotificationRegistrationState.registered;
    } on TransportException {
      registration = NotificationRegistrationState.serverUnavailable;
    } on ApiException catch (error) {
      registration = error.message == 'PUSH_PROVIDER_UNAVAILABLE'
          ? NotificationRegistrationState.providerUnavailable
          : NotificationRegistrationState.serverUnavailable;
    } on ProtocolException {
      registration = NotificationRegistrationState.serverUnavailable;
    }
  }

  Future<void> _retireServerBindingIfPossible() async {
    final token = _token;
    final owner = api.authenticatedUserId;
    if (token?.registeredOwner == null ||
        owner == null ||
        token!.registeredOwner != owner) {
      return;
    }
    try {
      final binding = api.capturePushSession();
      final clientUuid = await api.canonicalClientUuid();
      await api.unregisterPushDevice(
        clientUuid: clientUuid,
        session: binding,
      );
      _token = token.copyWith(clearRegisteredOwner: true);
      await tokenStore.write(_token!);
    } on Object {
      // Permission state remains truthful; registration is not reported active.
    }
  }

  Future<void> _retireNativeToken() async {
    final existing = _token;
    if (existing == null) {
      try {
        await nativeBridge.unregisterFromPush();
      } on Object {
        // Nothing durable to retry.
      }
      return;
    }
    _token = existing.copyWith(
      clearRegisteredOwner: true,
      retirePending: true,
    );
    await tokenStore.write(_token!);
    try {
      await nativeBridge.unregisterFromPush();
      _token = null;
      await tokenStore.clear();
    } on Object {
      // Retry before any future owner upload.
    }
  }

  Future<void> _retryPendingRetirement() async {
    if (_token?.retirePending != true) return;
    try {
      await nativeBridge.unregisterFromPush();
      _token = null;
      await tokenStore.clear();
    } on Object {
      registration = NotificationRegistrationState.providerUnavailable;
    }
  }

  Future<void> _publishRoute(PushRouteIntent intent) async {
    final handler = _routeHandler;
    if (handler == null) {
      if (_pendingRoutes.length >= 8) {
        _pendingRoutes.removeAt(0);
      }
      _pendingRoutes.add(intent);
      return;
    }
    await handler(intent);
  }

  Future<void> _drainPendingRoutes() async {
    final handler = _routeHandler;
    if (handler == null) return;
    while (_pendingRoutes.isNotEmpty && identical(_routeHandler, handler)) {
      final next = _pendingRoutes.removeAt(0);
      await handler(next);
    }
  }
}
