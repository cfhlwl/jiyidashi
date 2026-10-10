import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'account_delete_section.dart';
import 'amap_footprint_map.dart';
import 'amap_privacy_consent.dart';
import 'api_client.dart';
import 'auth_v3.dart';
import 'footprint_models.dart';
import 'location_sampling_coordinator.dart';
import 'media_presentation_cache.dart';
import 'memory_detail_page.dart';
import 'native_location_bridge.dart';
import 'native_location_controller.dart';
import 'native_location_section.dart';
import 'native_motion_sampling_bridge.dart';
import 'notification_client.dart';
import 'offline_queue.dart';
import 'offline_sync.dart';
import 'passive_memory_delivery.dart';
import 'phone_one_tap_bridge.dart';
import 'sms_otp.dart';
import 'wechat_auth_bridge.dart';
import 'onboarding_controller.dart';
import 'onboarding_flow.dart';
import 'onboarding_state.dart';
import 'place_detail_page.dart';
import 'recording_health_section.dart';
import 'reminder_page.dart';
import 'today_footprint_page.dart';
import 'timeline_models.dart';
import 'navigation/jiyi_navigation.dart';

// [人工注释][S1-026] AppShell 只接线 Onboarding；首次自动触发仅来自注册成功，老账号不会因缺少本地状态被误判为新用户。
import 'unified_capture_section.dart';
import 'ui/jiyi_theme.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';
import 'ui/jiyi_v3_components.dart';
import 'ui/jiyi_timezone.dart';
import 'v2/family_page.dart';
import 'v2/life_page.dart';
import 'v2/v2_home_page.dart';

class JiYiApp extends StatefulWidget {
  const JiYiApp({
    super.key,
    this.api,
    this.offlineQueue,
    this.onboardingStore,
    this.locationBridge,
    this.motionSamplingBridge,
    this.notificationClient,
    this.phoneOneTapBridge,
    this.wechatAuthGateway,
  });

  final JiYiApiClient? api;
  final OfflineQueueStore? offlineQueue;
  final OnboardingStateStore? onboardingStore;
  final NativeLocationBridge? locationBridge;
  final NativeMotionSamplingBridge? motionSamplingBridge;
  final NotificationClientService? notificationClient;
  final PhoneOneTapBridge? phoneOneTapBridge;
  final WechatAuthGateway? wechatAuthGateway;

  @override
  State<JiYiApp> createState() => _JiYiAppState();
}

class _JiYiAppState extends State<JiYiApp> with WidgetsBindingObserver {
  static const _themeModeStorageKey = 'jiyi.ui.theme-mode.v1';

  late final JiYiApiClient api = widget.api ?? JiYiApiClient();
  late final OfflineQueueStore offlineQueue =
      widget.offlineQueue ?? OfflineQueueStore();
  late final OfflineSyncCoordinator sync = OfflineSyncCoordinator(
    api: api,
    store: offlineQueue,
  );
  late final OnboardingStateStore onboardingStore =
      widget.onboardingStore ?? OnboardingStore();
  late final NativeLocationBridge locationBridge =
      widget.locationBridge ?? MethodChannelNativeLocationBridge();
  late final NativeMotionSamplingBridge motionSamplingBridge =
      widget.motionSamplingBridge ?? MethodChannelNativeMotionSamplingBridge();
  late final PassiveMemoryDeliveryCoordinator passiveDelivery =
      PassiveMemoryDeliveryCoordinator(
        api: api,
        store: offlineQueue,
        locationBridge: locationBridge,
        samplingBridge: motionSamplingBridge,
      );
  late final NotificationClientService notificationClient =
      widget.notificationClient ?? NotificationClientService(api: api);
  late final PhoneOneTapBridge phoneOneTapBridge =
      widget.phoneOneTapBridge ?? MethodChannelPhoneOneTapBridge();

  bool authenticated = false;
  AuthSessionVisualState _sessionState = AuthSessionVisualState.unknown;
  bool startOnboardingAfterAuth = false;
  bool resumeAccountDeletionAfterAuth = false;
  bool elderModeEnabled = false;
  ThemeMode _themeMode = ThemeMode.system;
  bool _themeModeChangedLocally = false;
  String? restoreMessage;
  Timer? _authorityRefreshTimer;
  Timer? _sessionRetryTimer;
  bool _coldRecoveryRetryUsed = false;
  StreamSubscription<void>? _passiveRecoveryRequests;
  final Completer<void> _initialRestoreFinished = Completer<void>();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(notificationClient.initialize());
    unawaited(_restoreThemeMode());
    final recoveryBridge = motionSamplingBridge;
    if (recoveryBridge is NativePassiveRecoveryTriggerBridge) {
      final triggerBridge =
          recoveryBridge as NativePassiveRecoveryTriggerBridge;
      _passiveRecoveryRequests =
          triggerBridge.passiveRecoveryRequests.listen((_) {
        unawaited(_handleNativePassiveRecoveryRequest());
      });
    }
    unawaited(
      _restoreServerSession().whenComplete(() {
        if (!_initialRestoreFinished.isCompleted) {
          _initialRestoreFinished.complete();
        }
      }),
    );
    _authorityRefreshTimer = Timer.periodic(
      const Duration(minutes: 5),
      (_) => unawaited(_refreshServerAuthority()),
    );
  }

  Future<void> _restoreThemeMode() async {
    try {
      final stored = await const FlutterSecureStorage().read(
        key: _themeModeStorageKey,
      );
      if (!mounted || _themeModeChangedLocally) return;
      final mode = switch (stored) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.system,
      };
      setState(() => _themeMode = mode);
    } catch (_) {
      // Appearance is a local preference. Storage failure must not block login or the shell.
    }
  }

  void _setThemeMode(ThemeMode mode) {
    _themeModeChangedLocally = true;
    setState(() => _themeMode = mode);
    final value = switch (mode) {
      ThemeMode.light => 'light',
      ThemeMode.dark => 'dark',
      ThemeMode.system => 'system',
    };
    unawaited(_persistThemeMode(value));
  }

  Future<void> _persistThemeMode(String value) async {
    try {
      await const FlutterSecureStorage().write(
        key: _themeModeStorageKey,
        value: value,
      );
    } catch (_) {
      // Appearance is a local preference. Storage failure must not block the shell.
    }
  }

  Future<bool> _awaitPassiveRecoveryIdle() async {
    if (motionSamplingBridge is! NativePassiveRecoveryTriggerBridge) {
      // Injected/test/unsupported bridges cannot host a competing native recovery engine.
      return true;
    }
    final recoveryBridge =
        motionSamplingBridge as NativePassiveRecoveryTriggerBridge;
    try {
      return await recoveryBridge
          .awaitPassiveRecoveryIdle()
          .timeout(const Duration(seconds: 95));
    } on MissingPluginException {
      // Widget/unit tests and unsupported platforms have no competing headless engine.
      return true;
    } on PlatformException {
      // Native arbitration failure is not permission to race a rotating refresh token.
      return false;
    } on TimeoutException {
      // Fail closed rather than allow a second engine to reuse the same refresh credential.
      return false;
    }
  }

  Future<void> _restoreServerSession() async {
    if (mounted) {
      setState(() => _sessionState = AuthSessionVisualState.refreshing);
    }
    if (!await _awaitPassiveRecoveryIdle()) {
      if (!mounted) return;
      setState(() {
        authenticated = false;
        _sessionState = AuthSessionVisualState.unknown;
        restoreMessage = null;
      });
      return;
    }
    if (!mounted) return;
    late final AuthRestoreStatus result;
    try {
      result = await api.restorePersistedSession();
    } on PlatformException {
      if (!mounted) return;
      setState(() {
        authenticated = false;
        _sessionState = AuthSessionVisualState.unknown;
        restoreMessage = null;
      });
      return;
    } catch (_) {
      if (!mounted) return;
      setState(() {
        authenticated = false;
        _sessionState = AuthSessionVisualState.unknown;
        restoreMessage = null;
      });
      return;
    }
    if (!mounted) return;
    if (result == AuthRestoreStatus.restored) {
      try {
        final profile = await api.getProfile();
        if (!mounted) return;
        setState(() {
          authenticated = true;
          _sessionState = AuthSessionVisualState.valid;
          restoreMessage = null;
          elderModeEnabled = profile['elder_mode_enabled'] == true;
        });
        unawaited(notificationClient.onAuthenticated());
        unawaited(_recoverPassiveMemory());
        return;
      } on ApiException catch (exc) {
        if (exc.statusCode == 423 &&
            exc.message == 'ACCOUNT_DELETION_IN_PROGRESS') {
          setState(() {
            authenticated = true;
            _sessionState = AuthSessionVisualState.valid;
            startOnboardingAfterAuth = false;
            resumeAccountDeletionAfterAuth = true;
            elderModeEnabled = false;
            restoreMessage = null;
          });
          unawaited(notificationClient.onAuthenticated());
          return;
        }
        if (isTerminalDurableSessionFailure(exc)) {
          final owner = api.authenticatedUserId?.trim();
          if (owner != null && owner.isNotEmpty) {
            await _disableNativeForTerminalAuthLoss(owner);
          }
          await notificationClient.onTerminalAuthLoss();
          if (!mounted) return;
          setState(() {
            authenticated = false;
            _sessionState = AuthSessionVisualState.signedOut;
            restoreMessage = '之前的登录状态已经失效，请重新登录。';
          });
          return;
        }
      } catch (_) {
        // Fall through to a safe unauthenticated state.
      }
    }

    setState(() {
      authenticated = false;
      _sessionState = result == AuthRestoreStatus.serverUnavailable
          ? AuthSessionVisualState.unknown
          : AuthSessionVisualState.signedOut;
      restoreMessage = null;
    });
    if (result == AuthRestoreStatus.serverUnavailable &&
        !_coldRecoveryRetryUsed) {
      _coldRecoveryRetryUsed = true;
      _sessionRetryTimer = Timer(const Duration(seconds: 3), () {
        _sessionRetryTimer = null;
        unawaited(_restoreServerSession());
      });
    }
  }

  Future<void> _handleNativePassiveRecoveryRequest() async {
    await _initialRestoreFinished.future;
    if (!mounted) return;

    var retry = false;
    var status = 'unexpected_failure';
    try {
      final report = await passiveDelivery.recoverAndDeliver(
        restoreSessionIfNeeded: !authenticated,
        allowProducerResume: true,
      );
      status = report.status.name;
      retry = switch (report.status) {
        PassiveMemoryRecoveryStatus.serverUnavailable ||
        PassiveMemoryRecoveryStatus.privacyUnavailable ||
        PassiveMemoryRecoveryStatus.retryableFailure ||
        PassiveMemoryRecoveryStatus.nativeUnavailable => true,
        _ => false,
      };

      if (report.status ==
          PassiveMemoryRecoveryStatus.accountDeletionInProgress) {
        if (mounted) {
          setState(() {
            authenticated = true;
            _sessionState = AuthSessionVisualState.valid;
            startOnboardingAfterAuth = false;
            resumeAccountDeletionAfterAuth = true;
            elderModeEnabled = false;
            restoreMessage = null;
          });
        }
      } else if (report.sessionRestored &&
          report.ownerUserId != null &&
          report.status != PassiveMemoryRecoveryStatus.noSession &&
          report.status != PassiveMemoryRecoveryStatus.authorityChanged) {
        // The coordinator already received a valid server profile before reaching this
        // point. Publish only the authenticated shell; AppShell refreshes elder preference.
        if (mounted) {
          setState(() {
            authenticated = true;
            _sessionState = AuthSessionVisualState.valid;
            resumeAccountDeletionAfterAuth = false;
            restoreMessage = null;
          });
          unawaited(notificationClient.onAuthenticated());
        }
      }
    } catch (_) {
      retry = true;
    } finally {
      try {
        await const MethodChannel('cn.jiyidashi/passive_recovery')
            .invokeMethod<void>(
          'complete',
          <String, Object?>{
            'status': status,
            'retry': retry,
          },
        );
      } on MissingPluginException {
        // Android uses the separate headless entrypoint; tests may have no native task.
      } on PlatformException {
        // iOS task expiration/rescheduling is the native fallback.
      }
    }
  }

  Future<void> _refreshServerAuthority() async {
    if (!authenticated) return;
    final owner = api.authenticatedUserId?.trim();
    try {
      await api.ensureFreshServerAuthority();
    } on ApiException catch (exc) {
      if (isTerminalDurableSessionFailure(exc)) {
        if (owner != null && owner.isNotEmpty) {
          await _disableNativeForTerminalAuthLoss(owner);
        }
        await notificationClient.onTerminalAuthLoss();
        if (!mounted) return;
        setState(() {
          authenticated = false;
          _sessionState = AuthSessionVisualState.signedOut;
          startOnboardingAfterAuth = false;
          resumeAccountDeletionAfterAuth = false;
          elderModeEnabled = false;
          restoreMessage = '登录状态已失效，请重新登录。';
        });
      }
    } on TransportException {
      // Keep the server-issued session material for a later retry, but never mint
      // local authority or silently replace it with cached user identity.
    }
  }

  Future<void> _disableNativeForTerminalAuthLoss(String owner) async {
    try {
      // Losing server/session authority must stop coordinate production immediately, but it
      // is not user consent to turn the feature off. Keep the explicit enabled owner so a
      // later authenticated recovery can resume after fresh Privacy verification.
      await locationBridge.pause(owner);
      final diagnosticBridge = locationBridge;
      if (diagnosticBridge is NativeLocationDiagnosticsBridge) {
        final diagnostics =
            diagnosticBridge as NativeLocationDiagnosticsBridge;
        await diagnostics.recordLocationLifecycleDiagnostic(
          owner,
          event: 'pause',
          reason: 'auth_session_terminal',
        );
      }
    } on MissingPluginException {
      // Auth state still fails closed even when this platform has no native bridge.
    } on PlatformException {
      // Do not restore authenticated UI merely because native shutdown could not report.
    }
  }

  Future<void> _recoverPassiveMemory() async {
    if (!authenticated || resumeAccountDeletionAfterAuth) return;
    try {
      await passiveDelivery.recoverAndDeliver(
        restoreSessionIfNeeded: false,
        allowProducerResume: true,
      );
    } catch (_) {
      // CORE-001 recovery is durable/fail-closed. UI authentication must not be
      // reinterpreted from a background delivery exception.
    }
  }

  Future<void> _resumeAuthorityAndPassiveMemory() async {
    await _refreshServerAuthority();
    await notificationClient.onAppResumed();
    if (authenticated) {
      await _recoverPassiveMemory();
    }
  }

  Future<void> _logout() async {
    try {
      try {
        await notificationClient.prepareForLogout();
      } catch (_) {
        // Auth logout still executes; server-side logout also fences the canonical
        // Device binding when the request reaches the backend.
      }
      await api.logout();
    } finally {
      if (mounted) {
        setState(() {
          authenticated = false;
          _sessionState = AuthSessionVisualState.signedOut;
          startOnboardingAfterAuth = false;
          resumeAccountDeletionAfterAuth = false;
          elderModeEnabled = false;
          restoreMessage = null;
        });
      }
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      if (_sessionState == AuthSessionVisualState.unknown && !authenticated) {
        unawaited(_restoreServerSession());
      } else {
        unawaited(_resumeAuthorityAndPassiveMemory());
      }
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _authorityRefreshTimer?.cancel();
    _sessionRetryTimer?.cancel();
    unawaited(_passiveRecoveryRequests?.cancel());
    if (widget.offlineQueue == null) {
      unawaited(offlineQueue.close());
    }
    if (widget.onboardingStore == null) {
      unawaited(onboardingStore.close());
    }
    if (widget.motionSamplingBridge == null) {
      unawaited(motionSamplingBridge.close());
    }
    if (widget.notificationClient == null) {
      unawaited(notificationClient.close());
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '迹忆',
      debugShowCheckedModeBanner: false,
      theme: JiYiTheme.light(elderMode: elderModeEnabled),
      darkTheme: JiYiTheme.dark(elderMode: elderModeEnabled),
      themeMode: _themeMode,
      home: switch (_sessionState) {
        AuthSessionVisualState.unknown || AuthSessionVisualState.refreshing =>
          const AuthV3NeutralBootstrap(),
        AuthSessionVisualState.valid => AppShell(
                  api: api,
                  offlineQueue: offlineQueue,
                  onboardingStore: onboardingStore,
                  startOnboarding: startOnboardingAfterAuth,
                  resumeAccountDeletion: resumeAccountDeletionAfterAuth,
                  locationBridge: locationBridge,
                  motionSamplingBridge: motionSamplingBridge,
                  passiveDelivery: passiveDelivery,
                  sync: sync,
                  themeMode: _themeMode,
                  onThemeModeChanged: _setThemeMode,
                  notificationClient: notificationClient,
                  onElderModeChanged: (enabled) {
                    if (mounted) setState(() => elderModeEnabled = enabled);
                  },
                  onLogout: () => unawaited(_logout()),
                ),
        AuthSessionVisualState.signedOut => AuthPage(
                  api: api,
                  capabilities: const AuthCapabilities.emailOnly(),
                  phoneOneTapBridge: phoneOneTapBridge,
                  wechatAuthGateway: widget.wechatAuthGateway,
                  authCapabilityLoader: api.fetchAuthCapabilities,
                  smsOtpGateway: api,
                  initialMessage: restoreMessage,
                  onRegistrationCompleted: () {
                    if (mounted) {
                      setState(() {
                        startOnboardingAfterAuth = true;
                        resumeAccountDeletionAfterAuth = false;
                      });
                    }
                  },
                  onAccountDeletionRecovery: () {
                    resumeAccountDeletionAfterAuth = true;
                    startOnboardingAfterAuth = false;
                  },
                  onAuthenticated: () {
                    if (mounted) {
                      setState(() {
                        authenticated = true;
                        _sessionState = AuthSessionVisualState.valid;
                        restoreMessage = null;
                      });
                      unawaited(notificationClient.onAuthenticated());
                      if (!resumeAccountDeletionAfterAuth) {
                        unawaited(_recoverPassiveMemory());
                      }
                    }
                  },
                ),
      },
    );
  }
}

class AuthPage extends StatefulWidget {
  const AuthPage({
    super.key,
    required this.api,
    required this.onAuthenticated,
    this.capabilities = const AuthCapabilities.emailOnly(),
    this.phoneOneTapBridge,
    this.wechatAuthGateway,
    this.authCapabilityLoader,
    this.privacyConsentGranted = false,
    this.onSmsOtp,
    this.smsOtpGateway,
    this.initialMessage,
    this.onRegistrationCompleted,
    this.onAccountDeletionRecovery,
  });

  final JiYiApiClient api;
  final VoidCallback onAuthenticated;
  final AuthCapabilities capabilities;
  final PhoneOneTapBridge? phoneOneTapBridge;
  final WechatAuthGateway? wechatAuthGateway;
  final AuthCapabilityLoader? authCapabilityLoader;
  final bool privacyConsentGranted;
  final VoidCallback? onSmsOtp;
  final SmsOtpGateway? smsOtpGateway;
  final String? initialMessage;
  final VoidCallback? onRegistrationCompleted;
  final VoidCallback? onAccountDeletionRecovery;

  @override
  State<AuthPage> createState() => _AuthPageState();
}

enum _AuthMode { login, register, verifyEmail, forgotPassword, resetPassword }

String _authProductMessage(String code) {
  return switch (code) {
    'EMAIL_VERIFICATION_REQUIRED' => '这个邮箱还没有完成验证。',
    'INVALID_CREDENTIALS' => '邮箱或密码不正确。',
    'AUTH_RATE_LIMITED' => '尝试次数较多，请稍后再试。',
    'INVALID_VERIFICATION_TOKEN' => '验证凭证无效，请重新发送验证邮件。',
    'VERIFICATION_TOKEN_EXPIRED' => '验证凭证已过期，请重新发送验证邮件。',
    'INVALID_PASSWORD_RESET_TOKEN' => '重置凭证无效，请重新申请。',
    'PASSWORD_RESET_TOKEN_EXPIRED' => '重置凭证已过期，请重新申请。',
    'AUTH_EMAIL_DELIVERY_UNAVAILABLE' => '邮件暂时没有发送成功，请稍后重试。',
    _ => '暂时无法完成操作，请稍后重试。',
  };
}


class _AuthPageState extends State<AuthPage> {
  final emailController = TextEditingController();
  final passwordController = TextEditingController();
  final nicknameController = TextEditingController();
  final tokenController = TextEditingController();
  late AuthCapabilities _capabilities;
  late bool _privacyConsentGranted;
  AuthCapabilityAuthority? _capabilityAuthority;
  int _capabilityGeneration = 0;
  int _authSurfaceGeneration = 0;
  _AuthMode mode = _AuthMode.login;
  bool loading = false;
  bool _phoneOneTapPending = false;
  bool obscurePassword = true;
  String? error;
  String? message;
  bool _phoneOneTapCancelling = false;
  bool _wechatAuthPending = false;
  bool _wechatAuthCancelling = false;

  @override
  void initState() {
    super.initState();
    // The first frame cannot trust injected provider availability. Every
    // non-email capability must be re-authorized by the current probe.
    _capabilities = widget.capabilities.failClosedNonEmail();
    _privacyConsentGranted = widget.privacyConsentGranted;
    _capabilityAuthority = AuthCapabilityAuthority(
      phoneOneTapBridge: widget.phoneOneTapBridge,
      wechatAuthGateway: widget.wechatAuthGateway,
      serverCapabilityLoader: widget.authCapabilityLoader,
    );
    if (_privacyConsentGranted) unawaited(_probeCapabilities());
    message = widget.initialMessage;
  }

  @override
  void dispose() {
    _authSurfaceGeneration += 1;
    if (_phoneOneTapPending || _wechatAuthPending) {
      widget.api.invalidateUnauthenticatedAuthGeneration();
      unawaited(
        widget.phoneOneTapBridge?.cancel().then<void>((_) {}) ??
            Future<void>.value(),
      );
      unawaited(
        widget.wechatAuthGateway?.cancel().then<void>((_) {}) ??
            Future<void>.value(),
      );
    }
    emailController.dispose();
    passwordController.dispose();
    nicknameController.dispose();
    tokenController.dispose();
    super.dispose();
  }

  Future<void> _probeCapabilities() async {
    final authority = _capabilityAuthority;
    if (authority == null || !_privacyConsentGranted) return;
    final generation = ++_capabilityGeneration;
    final capabilities = await authority.probe(
      privacyConsentGranted: _privacyConsentGranted,
      baseline: _capabilities,
    );
    if (!mounted || generation != _capabilityGeneration) return;
    setState(() => _capabilities = capabilities);
  }

  Future<void> _setPrivacyConsent(bool granted) async {
    if (granted == _privacyConsentGranted) return;
    if (!granted) {
      // The local authority is revoked before any native await. A provider
      // callback or backend response that arrives during cleanup is stale.
      _authSurfaceGeneration += 1;
      _capabilityGeneration += 1;
      final wasPending = _phoneOneTapPending;
      final wasWechatPending = _wechatAuthPending;
      _phoneOneTapPending = false;
      _phoneOneTapCancelling = wasPending;
      _wechatAuthPending = false;
      _wechatAuthCancelling = wasWechatPending;
      widget.api.invalidateUnauthenticatedAuthGeneration();
      if (mounted) {
        setState(() {
          _privacyConsentGranted = false;
          _capabilities = _capabilities.copyWith(
            phoneOneTapStatus: AuthCapabilityStatus.unavailable,
            smsOtpStatus: AuthCapabilityStatus.unavailable,
            wechatStatus: AuthCapabilityStatus.unavailable,
          );
        });
      }
      if (wasPending) {
        try {
          await widget.phoneOneTapBridge?.cancel();
        } catch (_) {
          // Privacy revocation remains fail closed even if native cleanup fails.
        }
      }
      if (wasWechatPending) {
        try {
          await widget.wechatAuthGateway?.cancel();
        } catch (_) {
          // Privacy revocation remains fail closed even if native cleanup fails.
        }
      }
      try {
        await widget.phoneOneTapBridge?.revokePrivacy();
      } catch (_) {
        // Privacy revocation remains fail closed even if native cleanup fails.
      }
      try {
        await widget.wechatAuthGateway?.revokePrivacy();
      } catch (_) {
        // Privacy revocation remains fail closed even if native cleanup fails.
      }
      if (mounted) {
        setState(() {
          _phoneOneTapCancelling = false;
          _wechatAuthCancelling = false;
        });
      }
      return;
    }

    setState(() => _privacyConsentGranted = true);
    await _probeCapabilities();
  }

  Future<void> _cancelPhoneOneTap() async {
    _authSurfaceGeneration += 1;
    widget.api.invalidateUnauthenticatedAuthGeneration();
    final wasPending = _phoneOneTapPending;
    _phoneOneTapPending = false;
    _phoneOneTapCancelling = wasPending;
    if (mounted) setState(() {});
    if (!wasPending) return;
    try {
      await widget.phoneOneTapBridge?.cancel();
    } catch (_) {
      // Cancellation is best effort; the generation fence still rejects late results.
    } finally {
      if (mounted) setState(() => _phoneOneTapCancelling = false);
    }
  }

  Future<void> _cancelWechat() async {
    _authSurfaceGeneration += 1;
    widget.api.invalidateUnauthenticatedAuthGeneration();
    final wasPending = _wechatAuthPending;
    _wechatAuthPending = false;
    _wechatAuthCancelling = wasPending;
    if (mounted) setState(() {});
    if (!wasPending) return;
    try {
      await widget.wechatAuthGateway?.cancel();
    } catch (_) {
      // The generation fence rejects any late credential.
    } finally {
      if (mounted) setState(() => _wechatAuthCancelling = false);
    }
  }

  bool _isCurrentAuthOperation(int generation) {
    return mounted && generation == _authSurfaceGeneration;
  }

  String _phoneOneTapError(PhoneOneTapState state) => switch (state) {
    PhoneOneTapState.cancelled => '',
    PhoneOneTapState.timeout => '本机号码登录响应超时，请使用邮箱登录。',
    PhoneOneTapState.unavailable => '当前暂时无法使用本机号码，请使用邮箱登录。',
    PhoneOneTapState.providerError => '本机号码登录暂时不可用，请使用邮箱登录。',
    PhoneOneTapState.available || PhoneOneTapState.tokenAcquired =>
      '暂时无法完成本机号码登录，请使用邮箱登录。',
  };

  Future<void> _startPhoneOneTap() async {
    if (_phoneOneTapPending ||
        _phoneOneTapCancelling ||
        !_capabilities.phoneOneTap) {
      return;
    }
    final bridge = widget.phoneOneTapBridge;
    if (bridge == null || !_privacyConsentGranted) {
      setState(() => error = '请先同意隐私政策后使用本机号码登录。');
      return;
    }
    final generation = ++_authSurfaceGeneration;
    setState(() {
      _phoneOneTapPending = true;
      error = null;
      message = null;
    });
    final coordinator = PhoneOneTapLoginCoordinator(
      bridge: bridge,
      exchangeClient: widget.api,
      clientPlatform: 'flutter',
    );
    try {
      final attempt = await coordinator.requestAttempt();
      if (!_isCurrentAuthOperation(generation)) return;
      await coordinator.exchange(attempt);
      if (!_isCurrentAuthOperation(generation)) return;
      widget.onAuthenticated();
    } on PhoneOneTapNativeException catch (exception) {
      if (!_isCurrentAuthOperation(generation)) return;
      final productError = _phoneOneTapError(exception.result.state);
      if (productError.isNotEmpty) setState(() => error = productError);
    } on ApiException catch (exception) {
      if (_isCurrentAuthOperation(generation)) {
        setState(() => error = _authProductMessage(exception.message));
      }
    } on TransportException {
      if (_isCurrentAuthOperation(generation)) {
        setState(() => error = '暂时无法连接服务器，请使用邮箱登录或稍后重试。');
      }
    } on ProtocolException {
      if (_isCurrentAuthOperation(generation)) {
        setState(() => error = '认证服务暂时不可用，请使用邮箱登录。');
      }
    } catch (_) {
      if (_isCurrentAuthOperation(generation)) {
        setState(() => error = '暂时无法完成本机号码登录，请使用邮箱登录。');
      }
    } finally {
      if (_isCurrentAuthOperation(generation)) {
        setState(() => _phoneOneTapPending = false);
      }
    }
  }

  String _wechatError(WechatAuthState state) => switch (state) {
    WechatAuthState.cancelled => '',
    WechatAuthState.timeout => '微信登录响应超时，请使用邮箱登录。',
    WechatAuthState.unavailable => '当前暂时无法使用微信登录，请使用邮箱登录。',
    WechatAuthState.providerError => '微信登录暂时不可用，请使用邮箱登录。',
    WechatAuthState.available || WechatAuthState.credentialAcquired =>
      '暂时无法完成微信登录，请使用邮箱登录。',
  };

  Future<void> _startWechat() async {
    if (_wechatAuthPending ||
        _wechatAuthCancelling ||
        !_capabilities.wechat ||
        !_privacyConsentGranted) {
      return;
    }
    final gateway = widget.wechatAuthGateway;
    if (gateway == null) return;
    final generation = ++_authSurfaceGeneration;
    setState(() {
      _wechatAuthPending = true;
      error = null;
      message = null;
    });
    final coordinator = WechatLoginCoordinator(
      gateway: gateway,
      exchangeClient: widget.api,
    );
    try {
      final attempt = await coordinator.requestAttempt();
      if (!_isCurrentAuthOperation(generation)) return;
      await coordinator.exchange(attempt);
      if (!_isCurrentAuthOperation(generation)) return;
      widget.onAuthenticated();
    } on WechatAuthNativeException catch (exception) {
      if (_isCurrentAuthOperation(generation)) {
        final productError = _wechatError(exception.result.state);
        if (productError.isNotEmpty) setState(() => error = productError);
      }
    } on ApiException {
      if (_isCurrentAuthOperation(generation)) {
        setState(() => error = '暂时无法完成微信登录，请使用邮箱登录。');
      }
    } on TransportException {
      if (_isCurrentAuthOperation(generation)) {
        setState(() => error = '暂时无法连接服务器，请使用邮箱登录或稍后重试。');
      }
    } on ProtocolException {
      if (_isCurrentAuthOperation(generation)) {
        setState(() => error = '认证服务暂时不可用，请使用邮箱登录。');
      }
    } catch (_) {
      if (_isCurrentAuthOperation(generation)) {
        setState(() => error = '暂时无法完成微信登录，请使用邮箱登录。');
      }
    } finally {
      if (_isCurrentAuthOperation(generation)) {
        setState(() => _wechatAuthPending = false);
      }
    }
  }

  Future<void> _switchToEmail() async {
    await _cancelPhoneOneTap();
    await _cancelWechat();
    if (!mounted) return;
    setState(() {
      mode = _AuthMode.login;
      error = null;
      message = null;
    });
  }

  Future<void> _submitCredentials() async {
    if (_phoneOneTapPending) await _cancelPhoneOneTap();
    if (emailController.text.trim().isEmpty || passwordController.text.isEmpty) {
      setState(() => error = '请输入邮箱和密码');
      return;
    }
    if (mode == _AuthMode.register && nicknameController.text.trim().isEmpty) {
      setState(() => error = '请输入昵称');
      return;
    }
    setState(() {
      loading = true;
      error = null;
      message = null;
    });
    try {
      if (mode == _AuthMode.register) {
        final registration = await widget.api.register(
          email: emailController.text,
          password: passwordController.text,
          nickname: nicknameController.text,
        );
        if (!mounted) return;
        final deliveryPending =
            registration['verification_delivery_pending'] == true;
        setState(() {
          mode = _AuthMode.verifyEmail;
          passwordController.clear();
          message = deliveryPending
              ? '账号已创建，但验证邮件暂时没有送达。请使用“重新发送验证邮件”。'
              : '验证邮件已发送。完成邮箱验证后才能进入你的记忆空间。';
        });
        return;
      }

      final login = await widget.api.login(
        email: emailController.text,
        password: passwordController.text,
      );
      if (login['account_deletion_in_progress'] == true) {
        widget.onAccountDeletionRecovery?.call();
      }
      widget.onAuthenticated();
    } on ApiException catch (exc) {
      if (exc.message == 'EMAIL_VERIFICATION_REQUIRED') {
        setState(() {
          mode = _AuthMode.verifyEmail;
          error = _authProductMessage(exc.message);
        });
      } else {
        setState(() => error = _authProductMessage(exc.message));
      }
    } on TransportException {
      setState(() => error = '暂时无法连接服务器');
    } on PlatformException {
      setState(() => error = '暂时无法读取或保存安全登录状态，请重新打开应用后重试。');
    } on MissingPluginException {
      setState(() => error = '暂时无法读取或保存安全登录状态，请重新打开应用后重试。');
    } on ProtocolException {
      setState(() => error = '认证服务响应格式不正确，请稍后重试。');
    } catch (_) {
      setState(() => error = '暂时无法完成登录操作，请稍后重试。');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _verifyEmail() async {
    if (tokenController.text.trim().isEmpty) {
      setState(() => error = '请输入验证邮件中的验证凭证');
      return;
    }
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final result = await widget.api.verifyEmail(tokenController.text);
      if (result['session'] != null) {
        widget.onRegistrationCompleted?.call();
        widget.onAuthenticated();
      } else if (mounted) {
        setState(() {
          mode = _AuthMode.login;
          message = '邮箱已经验证，请登录。';
          tokenController.clear();
        });
      }
    } on ApiException catch (exc) {
      setState(() => error = _authProductMessage(exc.message));
    } on TransportException {
      setState(() => error = '暂时无法连接服务器');
    } on PlatformException {
      setState(() => error = '暂时无法读取或保存安全登录状态，请重新打开应用后重试。');
    } on MissingPluginException {
      setState(() => error = '暂时无法读取或保存安全登录状态，请重新打开应用后重试。');
    } on ProtocolException {
      setState(() => error = '认证服务响应格式不正确，请稍后重试。');
    } catch (_) {
      setState(() => error = '暂时无法完成邮箱验证，请稍后重试。');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _resendVerification() async {
    if (emailController.text.trim().isEmpty) {
      setState(() => error = '请输入邮箱');
      return;
    }
    setState(() {
      loading = true;
      error = null;
    });
    try {
      await widget.api.resendVerification(emailController.text);
      if (mounted) setState(() => message = '如果账号可以验证，新的验证邮件已经发送。');
    } catch (_) {
      if (mounted) setState(() => error = '暂时无法发送验证邮件');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _requestReset() async {
    if (emailController.text.trim().isEmpty) {
      setState(() => error = '请输入邮箱');
      return;
    }
    setState(() {
      loading = true;
      error = null;
    });
    try {
      await widget.api.requestPasswordReset(emailController.text);
      if (!mounted) return;
      setState(() {
        mode = _AuthMode.resetPassword;
        tokenController.clear();
        passwordController.clear();
        message = '如果账号存在，密码重置邮件已经发送。';
      });
    } catch (_) {
      if (mounted) setState(() => error = '暂时无法提交重置请求');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _resetPassword() async {
    if (tokenController.text.trim().isEmpty || passwordController.text.isEmpty) {
      setState(() => error = '请输入重置凭证和新密码');
      return;
    }
    setState(() {
      loading = true;
      error = null;
    });
    try {
      await widget.api.resetPassword(
        token: tokenController.text,
        newPassword: passwordController.text,
      );
      if (!mounted) return;
      setState(() {
        mode = _AuthMode.login;
        tokenController.clear();
        passwordController.clear();
        message = '密码已更新，请重新登录。';
      });
    } on ApiException catch (exc) {
      setState(() => error = exc.message);
    } catch (_) {
      setState(() => error = '暂时无法重置密码');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  String get _title => switch (mode) {
        _AuthMode.login => '欢迎回来',
        _AuthMode.register => '创建你的记忆空间',
        _AuthMode.verifyEmail => '验证邮箱',
        _AuthMode.forgotPassword => '找回密码',
        _AuthMode.resetPassword => '设置新密码',
      };

  String get _subtitle => switch (mode) {
        _AuthMode.login => '登录后继续查看和管理属于你的可信记忆。',
        _AuthMode.register => '注册后先验证邮箱，再建立属于你的安全登录会话。',
        _AuthMode.verifyEmail => '验证完成前不会建立个人记忆空间的访问权限。',
        _AuthMode.forgotPassword => '提交后，无论账号是否存在都会得到相同结果。',
        _AuthMode.resetPassword => '重置成功会撤销这个账号现有的全部登录会话。',
      };

  bool get _useAuthV3Shell =>
      _capabilities.email ||
      _capabilities.phoneOneTap ||
      (_capabilities.smsOtp &&
          (widget.onSmsOtp != null || widget.smsOtpGateway != null)) ||
      (_capabilities.wechat && widget.wechatAuthGateway != null);

  Widget _buildPhoneOneTapEntry() {
    if (!_capabilities.phoneOneTap) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AuthV3PrimaryAction(
          key: const ValueKey('auth-v3-phone-one-tap'),
          label: _phoneOneTapPending ? '正在验证本机号码…' : '本机号码一键登录',
          icon: Icons.phone_iphone,
          onPressed: _phoneOneTapPending || _phoneOneTapCancelling
              ? null
              : _startPhoneOneTap,
        ),
        if (_capabilities.email) ...[
          const SizedBox(height: 8),
          TextButton(
            key: const ValueKey('auth-v3-email-fallback'),
            onPressed: _phoneOneTapPending ? _switchToEmail : null,
            child: const Text('使用邮箱登录'),
          ),
        ],
      ],
    );
  }

  Widget _buildSmsFallbackEntry() {
    if (!_capabilities.smsOtp ||
        (widget.onSmsOtp == null && widget.smsOtpGateway == null)) {
      return const SizedBox.shrink();
    }
    return AuthV3ProviderRow(
      key: const ValueKey('auth-v3-sms-fallback'),
      label: '手机号验证码登录',
      icon: Icons.sms_outlined,
      onPressed: _phoneOneTapPending
          ? null
          : widget.smsOtpGateway != null
              ? _openSmsOtp
              : widget.onSmsOtp,
    );
  }

  Widget _buildWechatEntry() {
    if (!_capabilities.wechat || widget.wechatAuthGateway == null) {
      return const SizedBox.shrink();
    }
    return AuthV3ProviderRow(
      key: const ValueKey('auth-v3-wechat-login'),
      label: _wechatAuthPending ? '正在打开微信…' : '微信登录',
      icon: Icons.chat_bubble_outline,
      iconColor: const Color(0xFF07B65A),
      leading: const AuthV3WeChatGlyph(),
      onPressed: _wechatAuthPending || _wechatAuthCancelling
          ? null
          : _startWechat,
    );
  }

  void _openSmsOtp() {
    final gateway = widget.smsOtpGateway;
    if (gateway == null) {
      widget.onSmsOtp?.call();
      return;
    }
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => SmsOtpPage(
          gateway: gateway,
          privacyConsentGranted: _privacyConsentGranted,
          onAuthenticated: () {
            widget.onAuthenticated();
            if (mounted) Navigator.of(context).pop();
          },
          onCancel: () {
            if (mounted) Navigator.of(context).pop();
          },
        ),
      ),
    );
  }

  Widget _buildProviderOnlySurface() {
    final hasPhone = _capabilities.phoneOneTap;
    final hasSms = _capabilities.smsOtp &&
        (widget.onSmsOtp != null || widget.smsOtpGateway != null);
    final hasWechat = _capabilities.wechat && widget.wechatAuthGateway != null;
    return Scaffold(
      backgroundColor: JiYiTodayVisuals.background,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(28, 180, 28, 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                '手机号登录',
                style: TextStyle(
                  color: JiYiTodayVisuals.navy,
                  fontSize: 24,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 10),
              const Text(
                '请选择当前可用的手机号认证方式。',
                style: TextStyle(
                  color: JiYiTodayVisuals.secondaryText,
                  fontSize: 16,
                ),
              ),
              const SizedBox(height: 28),
              if (hasPhone) _buildPhoneOneTapEntry(),
              if (hasPhone && hasSms) const SizedBox(height: 12),
              if (hasSms) _buildSmsFallbackEntry(),
              if (hasSms && hasWechat) const SizedBox(height: 12),
              if (hasWechat) _buildWechatEntry(),
              AuthV3Agreement(
                accepted: _privacyConsentGranted,
                onChanged: _setPrivacyConsent,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildEmailLoginV3Surface(BuildContext context) {
    final compactViewport = MediaQuery.sizeOf(context).height < 700;
    final fieldBorder = OutlineInputBorder(
      borderRadius: BorderRadius.circular(16),
      borderSide: const BorderSide(color: Color(0xFFE0E7EF)),
    );
    return Scaffold(
      backgroundColor: JiYiTodayVisuals.background,
      body: Stack(
        children: [
          const Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: AuthV3Hero(height: 300),
          ),
          SafeArea(
            bottom: false,
            child: SingleChildScrollView(
              padding: EdgeInsets.fromLTRB(
                28,
                compactViewport ? 150 : 218,
                28,
                20,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    '邮箱登录',
                    style: TextStyle(
                      color: JiYiTodayVisuals.navy,
                      fontSize: 24,
                      fontWeight: FontWeight.w800,
                      height: 1.2,
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    '请输入邮箱和密码',
                    style: TextStyle(
                      color: JiYiTodayVisuals.secondaryText,
                      fontSize: 16,
                      height: 1.4,
                    ),
                  ),
                  const SizedBox(height: 26),
                  TextField(
                    controller: emailController,
                    keyboardType: TextInputType.emailAddress,
                    textInputAction: TextInputAction.next,
                    decoration: InputDecoration(
                      hintText: '请输入邮箱地址',
                      prefixIcon: const Icon(Icons.mail_outline),
                      filled: true,
                      fillColor: JiYiTodayVisuals.card,
                      enabledBorder: fieldBorder,
                      focusedBorder: fieldBorder.copyWith(
                        borderSide: const BorderSide(
                          color: JiYiTodayVisuals.primaryBlue,
                          width: 1.5,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: passwordController,
                    obscureText: obscurePassword,
                    decoration: InputDecoration(
                      hintText: '请输入密码',
                      prefixIcon: const Icon(Icons.lock_outline),
                      suffixIcon: IconButton(
                        onPressed: () => setState(
                          () => obscurePassword = !obscurePassword,
                        ),
                        icon: Icon(
                          obscurePassword
                              ? Icons.visibility_off_outlined
                              : Icons.visibility_outlined,
                        ),
                      ),
                      filled: true,
                      fillColor: JiYiTodayVisuals.card,
                      enabledBorder: fieldBorder,
                      focusedBorder: fieldBorder.copyWith(
                        borderSide: const BorderSide(
                          color: JiYiTodayVisuals.primaryBlue,
                          width: 1.5,
                        ),
                      ),
                    ),
                  ),
                  if (message != null) ...[
                    const SizedBox(height: 12),
                    JiYiStatusBanner(
                      kind: JiYiStatusKind.info,
                      title: '提示',
                      message: message!,
                    ),
                  ],
                  if (error != null) ...[
                    const SizedBox(height: 12),
                    JiYiStatusBanner(
                      kind: JiYiStatusKind.error,
                      title: '未能继续',
                      message: error!,
                    ),
                  ],
                  const SizedBox(height: 22),
                  SizedBox(
                    height: 56,
                    child: FilledButton(
                      onPressed: loading ? null : _submitCredentials,
                      style: FilledButton.styleFrom(
                        backgroundColor: JiYiTodayVisuals.primaryBlue,
                        foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(16),
                        ),
                      ),
                      child: Text(loading ? '请稍候…' : '登录'),
                    ),
                  ),
                  TextButton(
                    onPressed: loading
                        ? null
                        : () => setState(() {
                            mode = _AuthMode.forgotPassword;
                            error = null;
                            message = null;
                          }),
                    child: const Text('忘记密码？'),
                  ),
                  _buildPhoneOneTapEntry(),
                  _buildSmsFallbackEntry(),
                  _buildWechatEntry(),
                  SizedBox(height: compactViewport ? 32 : 150),
                  Container(
                    height: 48,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: const Color(0xFFF4F7FB),
                      borderRadius: BorderRadius.circular(18),
                    ),
                    child: TextButton(
                      key: const ValueKey('auth-v3-register-entry'),
                      onPressed: loading
                          ? null
                          : () => setState(() {
                              mode = _AuthMode.register;
                              error = null;
                              message = null;
                            }),
                      child: const Text('没有账号？ 去注册'),
                    ),
                  ),
                  AuthV3Agreement(
                    accepted: _privacyConsentGranted,
                    onChanged: _setPrivacyConsent,
                  ),
                ],
              ),
            ),
          ),
          Positioned(
            top: 4,
            left: 10,
            child: SafeArea(
              bottom: false,
              child: IconButton(
                onPressed: () {},
                icon: const Icon(Icons.chevron_left),
                color: JiYiTodayVisuals.navy,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAuthV3Surface(BuildContext context) {
    if (mode == _AuthMode.login) {
      if (!_capabilities.email) return _buildProviderOnlySurface();
      return _buildEmailLoginV3Surface(context);
    }
    final theme = Theme.of(context);
    final compactViewport = MediaQuery.sizeOf(context).height < 700;
    final showPassword = mode == _AuthMode.login ||
        mode == _AuthMode.register ||
        mode == _AuthMode.resetPassword;
    if (!_capabilities.email) {
      return const Scaffold(
        backgroundColor: JiYiTodayVisuals.background,
        body: SafeArea(
          child: Center(
            child: Text(
              '当前暂时没有可用的登录方式',
              style: TextStyle(color: JiYiTodayVisuals.navy, fontSize: 16),
            ),
          ),
        ),
      );
    }
    return Scaffold(
      backgroundColor: JiYiTodayVisuals.background,
      body: Stack(
        children: [
          const Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: AuthV3Hero(height: 322),
          ),
          SafeArea(
            bottom: false,
            child: SingleChildScrollView(
              padding: EdgeInsets.fromLTRB(
                20,
                compactViewport ? 16 : 42,
                20,
                22,
              ),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    SizedBox(height: compactViewport ? 72 : 118),
                    AuthV3BrandLockup(compact: compactViewport),
                    SizedBox(height: compactViewport ? 36 : 92),
                    AuthV3Card(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(
                            mode == _AuthMode.login ? '邮箱登录' : _title,
                            style: const TextStyle(
                              color: JiYiTodayVisuals.navy,
                              fontSize: 24,
                              fontWeight: FontWeight.w800,
                              height: 1.2,
                            ),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            _subtitle,
                            style: const TextStyle(
                              color: JiYiTodayVisuals.secondaryText,
                              fontSize: 15,
                              height: 1.45,
                            ),
                          ),
                          const SizedBox(height: 18),
                          if (mode != _AuthMode.resetPassword) ...[
                            TextField(
                              controller: emailController,
                              keyboardType: TextInputType.emailAddress,
                              textInputAction: TextInputAction.next,
                              decoration: const InputDecoration(
                                labelText: '邮箱地址',
                                hintText: 'name@example.com',
                                prefixIcon: Icon(Icons.mail_outline),
                              ),
                            ),
                            const SizedBox(height: 12),
                          ],
                          if (showPassword)
                            TextField(
                              controller: passwordController,
                              obscureText: true,
                              decoration: InputDecoration(
                                labelText: mode == _AuthMode.resetPassword
                                    ? '新密码'
                                    : '密码',
                                prefixIcon: const Icon(Icons.lock_outline),
                              ),
                            ),
                          if (mode == _AuthMode.register) ...[
                            const SizedBox(height: 12),
                            TextField(
                              controller: nicknameController,
                              decoration: const InputDecoration(
                                labelText: '昵称',
                                prefixIcon: Icon(Icons.person_outline),
                              ),
                            ),
                          ],
                          if (mode == _AuthMode.verifyEmail ||
                              mode == _AuthMode.resetPassword) ...[
                            const SizedBox(height: 12),
                            TextField(
                              controller: tokenController,
                              autocorrect: false,
                              enableSuggestions: false,
                              decoration: InputDecoration(
                                labelText: mode == _AuthMode.verifyEmail
                                    ? '验证凭证'
                                    : '重置凭证',
                                prefixIcon: const Icon(Icons.key_outlined),
                              ),
                            ),
                          ],
                          if (message != null) ...[
                            const SizedBox(height: 12),
                            JiYiStatusBanner(
                              kind: JiYiStatusKind.info,
                              title: '提示',
                              message: message!,
                            ),
                          ],
                          if (error != null) ...[
                            const SizedBox(height: 12),
                            JiYiStatusBanner(
                              kind: JiYiStatusKind.error,
                              title: '未能继续',
                              message: error!,
                            ),
                          ],
                          const SizedBox(height: 18),
                          FilledButton(
                            onPressed: loading
                                ? null
                                : switch (mode) {
                                    _AuthMode.login ||
                                    _AuthMode.register =>
                                      _submitCredentials,
                                    _AuthMode.verifyEmail => _verifyEmail,
                                    _AuthMode.forgotPassword => _requestReset,
                                    _AuthMode.resetPassword => _resetPassword,
                                  },
                            style: FilledButton.styleFrom(
                              backgroundColor: JiYiTodayVisuals.primaryBlue,
                              foregroundColor: Colors.white,
                              minimumSize: const Size.fromHeight(56),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(16),
                              ),
                            ),
                            child: Text(
                              loading
                                  ? '请稍候…'
                                  : switch (mode) {
                                      _AuthMode.login => '登录',
                                      _AuthMode.register => '创建账号',
                                      _AuthMode.verifyEmail => '完成验证',
                                      _AuthMode.forgotPassword => '发送重置邮件',
                                      _AuthMode.resetPassword => '更新密码',
                                    },
                            ),
                          ),
                          if (mode == _AuthMode.verifyEmail) ...[
                            const SizedBox(height: 4),
                            TextButton(
                              onPressed: loading ? null : _resendVerification,
                              child: const Text('重新发送验证邮件'),
                            ),
                          ],
                          if (mode == _AuthMode.login) ...[
                            const SizedBox(height: 4),
                            TextButton(
                              onPressed: loading
                                  ? null
                                  : () => setState(() {
                                      mode = _AuthMode.forgotPassword;
                                      error = null;
                                      message = null;
                                    }),
                              child: const Text('忘记密码？'),
                            ),
                          ],
                          const SizedBox(height: 2),
                          TextButton(
                            onPressed: loading
                                ? null
                                : () => setState(() {
                                    mode = mode == _AuthMode.register
                                        ? _AuthMode.login
                                        : _AuthMode.register;
                                    error = null;
                                    message = null;
                                    tokenController.clear();
                                  }),
                            child: Text(
                              switch (mode) {
                                _AuthMode.login => '第一次使用？创建账号',
                                _AuthMode.register => '已有账号？返回登录',
                                _ => '返回登录 / 创建账号',
                              },
                            ),
                          ),
                        ],
                      ),
                    ),
                    AuthV3Agreement(
                      accepted: _privacyConsentGranted,
                      onChanged: _setPrivacyConsent,
                    ),
                    if (widget.api.showDevelopmentEndpoint)
                      Text(
                        '当前开发环境服务地址：${widget.api.baseUrl}',
                        textAlign: TextAlign.center,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: JiYiTodayVisuals.secondaryText,
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_useAuthV3Shell) return _buildAuthV3Surface(context);
    if (!_capabilities.email) {
      return const Scaffold(
        backgroundColor: JiYiTodayVisuals.background,
        body: SafeArea(
          child: Center(
            child: Text(
              '当前暂时没有可用的登录方式',
              style: TextStyle(color: JiYiTodayVisuals.navy, fontSize: 16),
            ),
          ),
        ),
      );
    }
    final theme = Theme.of(context);
    final showPassword = mode == _AuthMode.login ||
        mode == _AuthMode.register ||
        mode == _AuthMode.resetPassword;
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(
            JiYiSpacing.lg,
            JiYiSpacing.xxl,
            JiYiSpacing.lg,
            JiYiSpacing.xxl,
          ),
          children: [
            Align(
              alignment: Alignment.topCenter,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Align(
                      alignment: Alignment.centerLeft,
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          color: theme.colorScheme.primaryContainer,
                          borderRadius: BorderRadius.circular(JiYiRadius.large),
                        ),
                        child: Padding(
                          padding: const EdgeInsets.all(JiYiSpacing.sm),
                          child: Icon(
                            Icons.psychology_alt_outlined,
                            size: 28,
                            color: theme.colorScheme.onPrimaryContainer,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: JiYiSpacing.lg),
                    Text('迹忆', style: theme.textTheme.displaySmall),
                    const SizedBox(height: JiYiSpacing.xs),
                    Text(
                      '你负责生活，我帮你记住。',
                      style: theme.textTheme.titleMedium?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: JiYiSpacing.xxl),
                    JiYiSectionCard(
                      title: _title,
                      subtitle: _subtitle,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          if (mode != _AuthMode.resetPassword) ...[
                            TextField(
                              controller: emailController,
                              keyboardType: TextInputType.emailAddress,
                              textInputAction: TextInputAction.next,
                              decoration: const InputDecoration(
                                labelText: '邮箱',
                                hintText: 'name@example.com',
                                prefixIcon: Icon(Icons.mail_outline),
                              ),
                            ),
                            const SizedBox(height: JiYiSpacing.sm),
                          ],
                          if (showPassword)
                            TextField(
                              controller: passwordController,
                              obscureText: true,
                              decoration: InputDecoration(
                                labelText: mode == _AuthMode.resetPassword
                                    ? '新密码'
                                    : '密码',
                                prefixIcon: const Icon(Icons.lock_outline),
                              ),
                            ),
                          if (mode == _AuthMode.register) ...[
                            const SizedBox(height: JiYiSpacing.sm),
                            TextField(
                              controller: nicknameController,
                              decoration: const InputDecoration(
                                labelText: '昵称',
                                prefixIcon: Icon(Icons.person_outline),
                              ),
                            ),
                          ],
                          if (mode == _AuthMode.verifyEmail ||
                              mode == _AuthMode.resetPassword) ...[
                            const SizedBox(height: JiYiSpacing.sm),
                            TextField(
                              controller: tokenController,
                              autocorrect: false,
                              enableSuggestions: false,
                              decoration: InputDecoration(
                                labelText: mode == _AuthMode.verifyEmail
                                    ? '验证凭证'
                                    : '重置凭证',
                                prefixIcon: const Icon(Icons.key_outlined),
                              ),
                            ),
                          ],
                          if (message != null) ...[
                            const SizedBox(height: JiYiSpacing.sm),
                            JiYiStatusBanner(
                              kind: JiYiStatusKind.info,
                              title: '提示',
                              message: message!,
                            ),
                          ],
                          if (error != null) ...[
                            const SizedBox(height: JiYiSpacing.sm),
                            JiYiStatusBanner(
                              kind: JiYiStatusKind.error,
                              title: '未能继续',
                              message: error!,
                            ),
                          ],
                          const SizedBox(height: JiYiSpacing.md),
                          FilledButton(
                            onPressed: loading
                                ? null
                                : switch (mode) {
                                    _AuthMode.login ||
                                    _AuthMode.register =>
                                      _submitCredentials,
                                    _AuthMode.verifyEmail => _verifyEmail,
                                    _AuthMode.forgotPassword => _requestReset,
                                    _AuthMode.resetPassword => _resetPassword,
                                  },
                            child: Text(
                              loading
                                  ? '请稍候…'
                                  : switch (mode) {
                                      _AuthMode.login => '登录',
                                      _AuthMode.register => '创建账号',
                                      _AuthMode.verifyEmail => '完成验证',
                                      _AuthMode.forgotPassword => '发送重置邮件',
                                      _AuthMode.resetPassword => '更新密码',
                                    },
                            ),
                          ),
                          if (mode == _AuthMode.verifyEmail) ...[
                            const SizedBox(height: JiYiSpacing.xs),
                            TextButton(
                              onPressed: loading ? null : _resendVerification,
                              child: const Text('重新发送验证邮件'),
                            ),
                          ],
                          if (mode == _AuthMode.login) ...[
                            const SizedBox(height: JiYiSpacing.xs),
                            TextButton(
                              onPressed: loading
                                  ? null
                                  : () => setState(() {
                                      mode = _AuthMode.forgotPassword;
                                      error = null;
                                      message = null;
                                    }),
                              child: const Text('忘记密码？'),
                            ),
                          ],
                          const SizedBox(height: JiYiSpacing.xs),
                          TextButton(
                            onPressed: loading
                                ? null
                                : () => setState(() {
                                    mode = mode == _AuthMode.register
                                        ? _AuthMode.login
                                        : _AuthMode.register;
                                    error = null;
                                    message = null;
                                    tokenController.clear();
                                  }),
                            child: Text(
                              switch (mode) {
                                _AuthMode.login => '第一次使用？创建账号',
                                _AuthMode.register => '已有账号？返回登录',
                                _ => '返回登录 / 创建账号',
                              },
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (widget.api.showDevelopmentEndpoint) ...[
                      const SizedBox(height: JiYiSpacing.md),
                      Text(
                        '当前开发环境服务地址：${widget.api.baseUrl}',
                        textAlign: TextAlign.center,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class AppShell extends StatefulWidget {
  const AppShell({
    super.key,
    required this.api,
    required this.offlineQueue,
    this.onboardingStore,
    this.startOnboarding = false,
    this.resumeAccountDeletion = false,
    this.locationBridge,
    this.motionSamplingBridge,
    this.passiveDelivery,
    this.sync,
    this.mediaCache,
    this.amapPrivacyConsent,
    this.themeMode = ThemeMode.system,
    this.onThemeModeChanged,
    this.onElderModeChanged,
    this.notificationClient,
    required this.onLogout,
  });

  final JiYiApiClient api;
  final OfflineQueueStore offlineQueue;
  final OnboardingStateStore? onboardingStore;
  final bool startOnboarding;
  final bool resumeAccountDeletion;
  final NativeLocationBridge? locationBridge;
  final NativeMotionSamplingBridge? motionSamplingBridge;
  final PassiveMemoryDeliveryCoordinator? passiveDelivery;
  final OfflineSyncCoordinator? sync;
  final LocalMediaCache? mediaCache;
  final AmapPrivacyConsentAuthority? amapPrivacyConsent;
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode>? onThemeModeChanged;
  final ValueChanged<bool>? onElderModeChanged;
  final NotificationClientService? notificationClient;
  final VoidCallback onLogout;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> with WidgetsBindingObserver {
  late final OfflineSyncCoordinator _sync =
      widget.sync ?? OfflineSyncCoordinator(api: widget.api, store: widget.offlineQueue);
  late final LocalMediaCache _mediaCache =
      widget.mediaCache ?? LocalMediaCache();
  late final bool _ownsAmapPrivacyConsent =
      widget.amapPrivacyConsent is! AmapPrivacyConsentController;
  late final AmapPrivacyConsentController _amapPrivacyConsent =
      widget.amapPrivacyConsent is AmapPrivacyConsentController
          ? widget.amapPrivacyConsent! as AmapPrivacyConsentController
          : AmapPrivacyConsentController(delegate: widget.amapPrivacyConsent);
  int index = 0;
  int syncGeneration = 0;
  bool _accountDeletionIntentActive = false;
  bool _elderModeEnabled = false;
  OnboardingController? _onboarding;
  NativeLocationController? _nativeLocation;
  LocationSamplingCoordinator? _locationSampling;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    widget.notificationClient?.setRouteHandler(_handlePushRoute);
    _amapPrivacyConsent.addListener(_amapPrivacyChanged);
    unawaited(
      _amapPrivacyConsent.readAccepted().catchError((_) => false),
    );
    _accountDeletionIntentActive = widget.resumeAccountDeletion;
    if (_accountDeletionIntentActive) {
      index = JiYiDestination.profile.index;
    }
    final store = widget.onboardingStore;
    final owner = widget.api.authenticatedUserId?.trim();
    if (owner != null && owner.isNotEmpty) {
      final locationBridge =
          widget.locationBridge ?? MethodChannelNativeLocationBridge();
      final motionBridge =
          widget.motionSamplingBridge ?? MethodChannelNativeMotionSamplingBridge();
      final location = NativeLocationController(
        bridge: locationBridge,
        ownerUserId: owner,
      );
      _nativeLocation = location;
      final delivery = widget.passiveDelivery ??
          PassiveMemoryDeliveryCoordinator(
            api: widget.api,
            store: widget.offlineQueue,
            locationBridge: locationBridge,
            samplingBridge: motionBridge,
          );
      _locationSampling = LocationSamplingCoordinator(
        api: widget.api,
        store: widget.offlineQueue,
        locationController: location,
        nativeBridge: motionBridge,
        deliveryCoordinator: delivery,
        closeNativeBridgeOnDispose: widget.motionSamplingBridge == null,
      );
    }
    if (!_accountDeletionIntentActive &&
        store != null &&
        owner != null &&
        owner.isNotEmpty) {
      _onboarding = OnboardingController(
        store: store,
        ownerUserId: owner,
        autoStartForNewRegistration: widget.startOnboarding,
      )..addListener(_onboardingChanged);
    }

    unawaited(_refreshElderMode());

    // 登录进入生产 Shell 后立即尝试恢复当前账号的可重试 outbox。
    // coordinator 自身 single-flight，生命周期重复触发不会并发发送同一任务。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_accountDeletionIntentActive) {
        unawaited(_autoFlush());
      }
      final onboarding = _onboarding;
      if (onboarding != null) {
        unawaited(onboarding.initialize());
      }
      final location = _nativeLocation;
      if (location != null) {
        if (_accountDeletionIntentActive) {
          unawaited(location.disableForAccountDeletion());
        } else {
          // Native initialization only reads status. P subscribes/drains only after N's
          // authoritative privacy reconciliation; it never starts location by itself.
          unawaited(
            _initializeNativeLocation(location).then((_) async {
              if (!mounted || _accountDeletionIntentActive) return;
              await _locationSampling?.start();
            }),
          );
        }
      }
    });
  }

  void _amapPrivacyChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.notificationClient?.setRouteHandler(null);
    _amapPrivacyConsent.removeListener(_amapPrivacyChanged);
    if (_ownsAmapPrivacyConsent) {
      unawaited(_amapPrivacyConsent.close().catchError((_) {}));
      _amapPrivacyConsent.dispose();
    }
    _onboarding?.removeListener(_onboardingChanged);
    _onboarding?.dispose();
    _locationSampling?.dispose();
    _nativeLocation?.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(_autoFlush());
      final location = _nativeLocation;
      if (!_accountDeletionIntentActive && location != null) {
        // Returning from system settings is the authoritative point to observe permission
        // revocation/grant. Refresh never starts location by itself.
        unawaited(
          _initializeNativeLocation(location).then((_) async {
            if (!mounted || _accountDeletionIntentActive) return;
            await _locationSampling?.pump(forceFlush: true);
          }),
        );
      }
    }
  }

  Future<void> _refreshElderMode() async {
    final sessionVersion = widget.api.sessionVersion;
    final owner = widget.api.authenticatedUserId;
    try {
      final profile = await widget.api.getProfile();
      if (!mounted ||
          widget.api.sessionVersion != sessionVersion ||
          widget.api.authenticatedUserId != owner) {
        return;
      }
      final enabled = profile['elder_mode_enabled'] == true;
      setState(() => _elderModeEnabled = enabled);
      widget.onElderModeChanged?.call(enabled);
    } catch (_) {
      if (!mounted ||
          widget.api.sessionVersion != sessionVersion ||
          widget.api.authenticatedUserId != owner) {
        return;
      }
      setState(() => _elderModeEnabled = false);
      widget.onElderModeChanged?.call(false);
    }
  }

  Future<void> _initializeNativeLocation(
    NativeLocationController location,
  ) async {
    await location.initialize();
    if (!mounted || _accountDeletionIntentActive) return;

    // Server privacy is authoritative. A producer that survived process/engine lifecycle
    // must be quarantined immediately after status() and before any network wait; otherwise
    // "privacy unknown" would still leak production time while getPrivacyStatus is slow.
    final restoreAfterVerification =
        await location.quarantineForPrivacyVerification();
    if (!mounted || _accountDeletionIntentActive) return;
    await _reconcileNativeLocationPrivacy(
      location,
      restoreAfterVerification: restoreAfterVerification,
    );
  }

  Future<void> _reconcileNativeLocationPrivacy(
    NativeLocationController location, {
    required bool restoreAfterVerification,
  }) async {
    try {
      final privacy = await widget.api.getPrivacyStatus();
      if (!mounted || _accountDeletionIntentActive) return;
      if (privacy['recording_paused'] == true) {
        await location.pauseForPrivacy();
      } else if (restoreAfterVerification) {
        // Restore only the producer that was verifiably running before quarantine.
        // This path calls start only; it can never request or upgrade location permission.
        await location.resumeVerifiedProducerAfterQuarantine();
      } else {
        // An already-stopped producer remains stopped on login/app resume.
        location.markPrivacyActive();
      }
    } catch (_) {
      if (!mounted || _accountDeletionIntentActive) return;
      await location.privacyStatusUnknown();
    }
  }

  Future<void> _revalidateNativeLocationAuthority() async {
    final location = _nativeLocation;
    if (location == null || _accountDeletionIntentActive) return;
    await _reconcileNativeLocationPrivacy(
      location,
      restoreAfterVerification: false,
    );
    if (!mounted || _accountDeletionIntentActive) return;
    // Native status is an independent authority boundary. refresh() is read-only:
    // it cannot request permission or start location production.
    await location.refresh();
  }

  Future<void> _handlePushRoute(PushRouteIntent intent) async {
    if (!mounted || _accountDeletionIntentActive) return;

    switch (intent.destination) {
      case NotificationDestination.home:
      case NotificationDestination.appUpdate:
      case NotificationDestination.export:
        Navigator.of(context).popUntil((route) => route.isFirst);
        if (mounted) setState(() => index = JiYiDestination.today.index);
        return;
      case NotificationDestination.family:
        Navigator.of(context).popUntil((route) => route.isFirst);
        if (mounted) setState(() => index = JiYiDestination.family.index);
        return;
      case NotificationDestination.reminder:
        await JiYiNavigator.push<void>(
          context,
          builder: (_) => ReminderPage(api: widget.api),
        );
        return;
      case NotificationDestination.memory:
        final memoryId = intent.resourceId;
        if (memoryId == null) {
          if (mounted) setState(() => index = JiYiDestination.today.index);
          return;
        }
        await JiYiNavigator.pushDetail<void>(
          context,
          builder: (_) => MemoryDetailPage(
            api: widget.api,
            memoryId: memoryId,
            mediaCache: _mediaCache,
            amapPrivacyConsent: _amapPrivacyConsent,
          ),
        );
        return;
    }
  }

  Future<void> _stopLocationAndLogout() async {
    // Seal sampling first so a late native event cannot enqueue/upload after logout begins.
    await _locationSampling?.suspendForLogout();
    final location = _nativeLocation;
    if (location != null) {
      await location.stopForLogout();
    }
    if (mounted) widget.onLogout();
  }

  Future<void> _autoFlush() async {
    if (_accountDeletionIntentActive) return;
    final owner = widget.api.authenticatedUserId;
    if (owner == null || owner.trim().isEmpty) return;
    try {
      // 空队列直接返回，既避免无意义的数据库/网络调度，也让只提供计数 seam
      // 的视觉测试不必打开真实 SQLite。数据库首次打开仍会先恢复 interrupted sending。
      final awaiting = await widget.offlineQueue.countAwaitingDelivery(owner);
      if (awaiting == 0) return;
      await _sync.flush(owner);
    } catch (_) {
      // 自动同步失败时只保留 SQLite 的真实状态，不能把本地任务伪装成 completed。
    } finally {
      if (mounted) setState(() => syncGeneration += 1);
    }
  }

  Future<void> _prepareLocalAccountDeletion() async {
    final owner = widget.api.authenticatedUserId?.trim();
    if (owner == null || owner.isEmpty) {
      throw StateError('authenticated user id missing during account deletion');
    }
    if (mounted) {
      setState(() {
        // [人工注释][S1-022-FIX-002] 一旦用户确认不可逆注销，立即封住普通导航与新的自动同步；
        // 即使后续服务端返回 202/网络失败，也不能重新进入会产生本地数据的普通工作流。
        _accountDeletionIntentActive = true;
        index = JiYiDestination.profile.index;
      });
    }
    // [人工注释][S1-022][S2-004/005] 注销确认后的所有 owner-local producer gate
    // 必须在第一次 await 之前同步建立。P 的 quiesce() 进入函数即先置 _quiesced=true，
    // OfflineQueue/Sync 也立即封住新写入/发送；后续只等待已经在飞的旧 Future 收尾。
    final samplingIdle =
        _locationSampling?.quiesceForAccountDeletion();
    final offlineQueueIdle =
        widget.offlineQueue.quiesceForAccountDeletion(owner);
    final syncIdle = _sync.quiesceForAccountDeletion(owner);

    try {
      await widget.notificationClient?.prepareForLogout();
    } catch (_) {
      // Native token retirement is retried from secure pending state. The account
      // deletion backend also removes the canonical Device authority.
    }

    final location = _nativeLocation;
    if (location != null) {
      // Account deletion clears this account's automatic-location enablement before
      // local data purge, so a later account on the same device cannot inherit it.
      await location.disableForAccountDeletion();
    }

    final onboarding = _onboarding;
    if (onboarding != null) {
      // [人工注释][S1-022-FIX-006] 先等账号作用域 onboarding 写入完全停住，再删本地行；
      // purge 必须是该 owner 在本机的最后一次 onboarding 持久化动作。
      await onboarding.quiesceForAccountDeletion();
      onboarding.removeListener(_onboardingChanged);
      onboarding.dispose();
      _onboarding = null;
    }
    if (samplingIdle != null) {
      await samplingIdle;
    }
    await offlineQueueIdle;
    await syncIdle;
    // All producers are now sealed and drained; this transaction is the final owner-local
    // SQLite payload write/delete boundary for Stage 1 + Stage 2 raw location rows.
    await widget.offlineQueue.purgeOwner(owner);
    await _mediaCache.purgeOwner(owner);
    final localOnboarding = widget.onboardingStore;
    if (localOnboarding != null) {
      await localOnboarding.deleteOwnerState(owner);
    }
  }

  void _queueChanged() {
    if (mounted) setState(() => syncGeneration += 1);
  }

  void _onboardingChanged() {
    final onboarding = _onboarding;
    if (!mounted || onboarding == null) return;
    final targetIndex = onboarding.navigationIndex;
    setState(() {
      if (targetIndex != null) index = targetIndex;
    });
  }

  @override
  Widget build(BuildContext context) {
    final onboarding = _onboarding;
    final onboardingStep = onboarding?.step;
    final capturePage = CapturePage(
      api: widget.api,
      offlineQueue: widget.offlineQueue,
      sync: _sync,
      syncGeneration: syncGeneration,
      onQueueChanged: _queueChanged,
      mediaCache: _mediaCache,
      elderMode: _elderModeEnabled,
      onAuthoritativeTextMemorySaved:
          onboardingStep == OnboardingStep.capture
              ? onboarding?.authoritativeTextMemorySaved
              : null,
    );
    final memoryPage = MemoryQueryPage(
      key: ValueKey('memory-map-consent-${_amapPrivacyConsent.accepted}'),
      api: widget.api,
      mediaCache: _mediaCache,
      amapPrivacyConsent: _amapPrivacyConsent,
      notificationClient: widget.notificationClient,
      elderMode: _elderModeEnabled,
      onCapture: () {
        unawaited(
          JiYiNavigator.push<void>(
            context,
            builder: (_) => capturePage,
          ),
        );
      },
      initialQuestion: onboardingStep == OnboardingStep.retrieve ||
              onboardingStep == OnboardingStep.trust
          ? onboarding?.querySeed
          : null,
      requiredEvidenceMemoryId: onboardingStep == OnboardingStep.retrieve ||
              onboardingStep == OnboardingStep.trust
          ? onboarding?.targetMemoryId
          : null,
      onTrustedEvidenceShown: onboardingStep == OnboardingStep.retrieve
          ? onboarding?.trustedEvidenceShown
          : null,
    );
    final pagesByDestination = <JiYiDestination, Widget>{
      JiYiDestination.today: TodayPage(
        key: ValueKey('today-map-consent-${_amapPrivacyConsent.accepted}'),
        api: widget.api,
        mediaCache: _mediaCache,
        amapPrivacyConsent: _amapPrivacyConsent,
        elderMode: _elderModeEnabled,
        onCapture: () {
          unawaited(
            JiYiNavigator.push<void>(
              context,
              builder: (_) => capturePage,
            ),
          );
        },
        onOpenFamily: () => setState(() => index = JiYiDestination.family.index),
      ),
      JiYiDestination.memory: memoryPage,
      JiYiDestination.life: LifePage(
        api: widget.api,
        mediaCache: _mediaCache,
      ),
      JiYiDestination.family: FamilyPage(
        api: widget.api,
        mediaCache: _mediaCache,
        amapPrivacyConsent: _amapPrivacyConsent,
      ),
      JiYiDestination.profile: ProfilePage(
        api: widget.api,
        onElderModeChanged: (enabled) {
          setState(() => _elderModeEnabled = enabled);
          widget.onElderModeChanged?.call(enabled);
        },
        onLogout: () => unawaited(_stopLocationAndLogout()),
        onAccountDeleteIntentConfirmed: _prepareLocalAccountDeletion,
        onAccountDeleted: () async => _stopLocationAndLogout(),
        resumeAccountDeletion: _accountDeletionIntentActive,
        nativeLocationController: _nativeLocation,
        offlineQueue: widget.offlineQueue,
        onRevalidateLocationAuthority: _revalidateNativeLocationAuthority,
        onStartOnboarding: onboarding == null
            ? null
            : () => unawaited(onboarding.restart()),
        amapPrivacyConsent: _amapPrivacyConsent,
        themeMode: widget.themeMode,
        onThemeModeChanged: widget.onThemeModeChanged,
      ),
    };
    final pages = JiYiDestinationCatalog.buildPages(
      (destination) => pagesByDestination[destination]!,
    );
    final onboardingExperience = OnboardingExperience(
      step: _accountDeletionIntentActive ? null : onboardingStep,
      onStart: onboarding?.startFlow ?? () {},
      onSkip: () {
        if (onboarding != null) unawaited(onboarding.skip());
      },
      onComplete: () {
        if (onboarding != null) unawaited(onboarding.complete());
      },
      child: onboardingStep == OnboardingStep.capture
          ? capturePage
          : pages[index],
    );
    final todayVisualShell =
        onboardingStep == null &&
            !_accountDeletionIntentActive &&
            index == JiYiDestination.today.index;
    return Scaffold(
      body: todayVisualShell
          ? onboardingExperience
          : SafeArea(child: onboardingExperience),
      // [人工注释][S1-026] 引导进行时由 GuideBar 提供唯一退出入口；隐藏而不是保留“看得见但点不动”的底部导航。
      floatingActionButton:
          onboardingStep != null ||
                  _accountDeletionIntentActive ||
                  index == JiYiDestination.today.index ||
                  index == JiYiDestination.memory.index
              ? null
              : FloatingActionButton.extended(
                  onPressed: () {
                    unawaited(
                      JiYiNavigator.push<void>(
                        context,
                        builder: (_) => capturePage,
                      ),
                    );
                  },
                  icon: const Icon(Icons.edit_outlined),
                  label: const Text('记一下'),
                ),
      bottomNavigationBar: !JiYiShellPolicy.showBottomNavigation(
        onboardingActive: onboardingStep != null,
        accountDeletionActive: _accountDeletionIntentActive,
      )
          ? null
          : _JiYiBottomNavigation(
              selectedIndex: index,
              onDestinationSelected: (value) => setState(() => index = value),
            ),
    );
  }
}

class _JiYiBottomNavigation extends StatelessWidget {
  const _JiYiBottomNavigation({
    required this.selectedIndex,
    required this.onDestinationSelected,
  });

  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: JiYiTodayVisuals.card,
        boxShadow: [
          BoxShadow(
            color: Color(0x0D152D4B),
            blurRadius: 14,
            offset: Offset(0, -2),
          ),
        ],
      ),
      child: Padding(
        padding: EdgeInsets.only(bottom: bottomInset),
        child: SizedBox(
          height: JiYiTodayGeometry.bottomNavigationContentHeight,
          child: Row(
            children: [
              for (final descriptor in JiYiDestinationCatalog.descriptors)
                Expanded(
                  child: _JiYiBottomNavigationItem(
                    icon: descriptor.icon,
                    selectedIcon: descriptor.selectedIcon,
                    label: descriptor.label,
                    selected: JiYiDestinationCatalog.isSelected(
                      descriptor.destination,
                      selectedIndex,
                    ),
                    onTap: () => onDestinationSelected(descriptor.index),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _JiYiBottomNavigationItem extends StatelessWidget {
  const _JiYiBottomNavigationItem({
    required this.icon,
    required this.selectedIcon,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final IconData icon;
  final IconData selectedIcon;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = selected
        ? JiYiTodayVisuals.primaryBlue
        : JiYiTodayVisuals.secondaryText;
    return Semantics(
      key: ValueKey<String>('bottom-nav-$label'),
      container: true,
      button: true,
      selected: selected,
      label: label,
      onTap: onTap,
      child: ExcludeSemantics(
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            onTap: onTap,
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(selected ? selectedIcon : icon, size: 23, color: color),
                const SizedBox(height: 1),
                Text(
                  label,
                  maxLines: 1,
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: color,
                    fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                    height: 1,
                  ),
                ),
                const SizedBox(height: 2),
                AnimatedContainer(
                  duration: JiYiMotion.fast,
                  curve: JiYiMotion.easing,
                  width: selected ? 28 : 0,
                  height: 3,
                  decoration: BoxDecoration(
                    color: color,
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class TimelinePage extends StatefulWidget {
  const TimelinePage({
    super.key,
    required this.api,
    this.mediaCache,
    this.photoThumbnailBuilder,
    this.elderMode = false,
    this.amapPrivacyConsent,
  });

  final JiYiApiClient api;
  final LocalMediaCache? mediaCache;
  final LocalMediaThumbnailBuilder? photoThumbnailBuilder;
  final bool elderMode;
  final AmapPrivacyConsentAuthority? amapPrivacyConsent;

  @override
  State<TimelinePage> createState() => _TimelinePageState();
}

class _TimelinePageState extends State<TimelinePage> {
  final List<TimelineReadItem> _items = [];
  String? _nextCursor;
  String? _error;
  bool _offline = false;
  bool _loading = true;
  bool _loadingMore = false;
  int _requestEpoch = 0;
  String? _timezone;
  String? _day;

  @override
  void initState() {
    super.initState();
    _loadInitial();
  }

  bool _requestCurrent(int epoch, int sessionVersion, String? ownerId) {
    return mounted &&
        epoch == _requestEpoch &&
        widget.api.sessionVersion == sessionVersion &&
        widget.api.authenticatedUserId == ownerId;
  }

  Future<void> _loadInitial() async {
    final epoch = ++_requestEpoch;
    final sessionVersion = widget.api.sessionVersion;
    final ownerId = widget.api.authenticatedUserId;
    setState(() {
      _loading = true;
      _offline = false;
      _error = null;
    });
    try {
      final raw = await widget.api.getTimelineEvents(limit: 30);
      if (!_requestCurrent(epoch, sessionVersion, ownerId)) return;
      final page = TimelineReadPage.parse(raw);
      setState(() {
        _items
          ..clear()
          ..addAll(page.items);
        _nextCursor = page.nextCursor;
        _timezone = page.timezone;
        _day = page.day;
        _loading = false;
      });
    } on TransportException {
      if (!_requestCurrent(epoch, sessionVersion, ownerId)) return;
      setState(() {
        _loading = false;
        _offline = true;
      });
    } on ProtocolException {
      if (!_requestCurrent(epoch, sessionVersion, ownerId)) return;
      setState(() {
        _loading = false;
        _error = '时间线数据暂时无法识别，可以重新加载。';
      });
    } on ApiException catch (exc) {
      if (!_requestCurrent(epoch, sessionVersion, ownerId)) return;
      setState(() {
        _loading = false;
        _error = exc.statusCode == 401
            ? '登录状态已失效，请重新登录。'
            : '时间线暂时无法读取，可以稍后重试。';
      });
    } catch (_) {
      if (!_requestCurrent(epoch, sessionVersion, ownerId)) return;
      setState(() {
        _loading = false;
        _error = '时间线暂时无法读取，可以稍后重试。';
      });
    }
  }

  Future<void> _loadMore() async {
    final cursor = _nextCursor;
    if (cursor == null || _loadingMore) return;
    final epoch = _requestEpoch;
    final sessionVersion = widget.api.sessionVersion;
    final ownerId = widget.api.authenticatedUserId;
    setState(() {
      _loadingMore = true;
      _error = null;
    });
    try {
      final raw = await widget.api.getTimelineEvents(
        limit: 30,
        cursor: cursor,
      );
      if (!_requestCurrent(epoch, sessionVersion, ownerId)) return;
      final page = TimelineReadPage.parse(raw);
      if (page.timezone != _timezone || page.day != _day) {
        throw ProtocolException('时间线分页范围发生变化');
      }
      final seen = _items.map((item) => '${item.kind}:${item.id}').toSet();
      for (final item in page.items) {
        if (!seen.add('${item.kind}:${item.id}')) {
          throw ProtocolException('时间线分页包含重复记录');
        }
      }
      setState(() {
        _items.addAll(page.items);
        _nextCursor = page.nextCursor;
        _loadingMore = false;
      });
    } on ProtocolException {
      if (!_requestCurrent(epoch, sessionVersion, ownerId)) return;
      setState(() {
        _loadingMore = false;
        _error = '更多时间线记录暂时无法验证，请重新加载。';
      });
    } on TransportException {
      if (!_requestCurrent(epoch, sessionVersion, ownerId)) return;
      setState(() {
        _loadingMore = false;
        _error = '网络连接中断，可以稍后继续加载。';
      });
    } catch (_) {
      if (!_requestCurrent(epoch, sessionVersion, ownerId)) return;
      setState(() {
        _loadingMore = false;
        _error = '更多时间线记录暂时无法读取。';
      });
    }
  }

  void _openItem(TimelineReadItem item) {
    if (item.isMemory) {
      unawaited(
        JiYiNavigator.pushDetail<bool>(
          context,
          builder: (_) => MemoryDetailPage(
            api: widget.api,
            memoryId: item.id,
            mediaCache: widget.mediaCache,
            amapPrivacyConsent: widget.amapPrivacyConsent,
          ),
        ),
      );
      return;
    }
    final placeId = item.placeId;
    if (placeId == null) return;
    unawaited(
      JiYiNavigator.pushDetail<void>(
        context,
        builder: (_) => PlaceDetailPage(
          api: widget.api,
          placeId: placeId,
          amapPrivacyConsent: widget.amapPrivacyConsent,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return V3PageScaffold(
      title: '时间线',
      subtitle: '按时间回看生活里的片段。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_loading)
            const V3StateSurface(
              variant: V3StateSurfaceVariant.loading,
              title: '正在整理时间线…',
              message: '正在读取已经形成的真实记录。',
              icon: Icons.timeline_outlined,
            )
          else if (_offline)
            V3StateSurface(
              variant: V3StateSurfaceVariant.offline,
              title: '当前离线',
              message: '网络连接后可以继续读取时间线。',
              icon: Icons.cloud_off_outlined,
              primaryAction: V3StateAction(
                label: '重新连接',
                icon: Icons.refresh,
                onPressed: _loadInitial,
              ),
            )
          else if (_error != null && _items.isEmpty)
            V3StateSurface(
              variant: V3StateSurfaceVariant.error,
              title: '时间线暂时不可用',
              message: _error!,
              icon: Icons.timeline_outlined,
              primaryAction: V3StateAction(
                label: '重新打开',
                icon: Icons.refresh,
                onPressed: _loadInitial,
              ),
            )
          else if (_items.isEmpty)
            const V3StateSurface(
              variant: V3StateSurfaceVariant.empty,
              icon: Icons.timeline_outlined,
              title: '还没有时间线记录',
              message: '记下一件事或形成到访后，这里会按时间慢慢串起来。',
            )
          else ...[
            const V3SectionHeader(
              title: '最近的记录',
              subtitle: '按时间从新到旧排列。',
            ),
            const SizedBox(height: JiYiSpacing.md),
            for (var index = 0; index < _items.length; index++) ...[
              if (_startsNewTimelineMonth(index))
                _TimelineDayHeader(
                  item: _items[index],
                  timezone: _timezone,
                ),
              _TimelineEntry(
                api: widget.api,
                item: _items[index],
                timezone: _timezone,
                mediaCache: widget.mediaCache,
                photoThumbnailBuilder: widget.photoThumbnailBuilder,
                isLast: index == _items.length - 1,
                onTap: () => _openItem(_items[index]),
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: JiYiSpacing.sm),
              JiYiStatusBanner(
                kind: JiYiStatusKind.error,
                message: _error!,
              ),
            ],
            if (_nextCursor != null) ...[
              const SizedBox(height: JiYiSpacing.md),
              OutlinedButton.icon(
                onPressed: _loadingMore ? null : _loadMore,
                icon: _loadingMore
                    ? const SizedBox.square(
                        dimension: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.expand_more),
                label: Text(_loadingMore ? '正在加载…' : '查看更多'),
              ),
            ],
          ],
          if (!widget.elderMode) ...[
            const SizedBox(height: JiYiSpacing.lg),
            JiYiActionCard(
              icon: Icons.hub_outlined,
              title: '重要的人和人生故事',
              message: '查看你记录的重要的人、人生阶段和重要经历。',
              onTap: () {
                unawaited(
                  JiYiNavigator.pushDetail<void>(
                    context,
                    builder: (_) => V2HomePage(
                      api: widget.api,
                      mediaCache: widget.mediaCache,
                    ),
                  ),
                );
              },
            ),
          ],
        ],
      ),
    );
  }

  bool _startsNewTimelineMonth(int index) {
    if (index == 0) return true;
    final previous = _timelineWallClock(_items[index - 1].occurredAt);
    final current = _timelineWallClock(_items[index].occurredAt);
    return previous.year != current.year ||
        previous.month != current.month;
  }

  DateTime _timelineWallClock(String value) {
    return jiyiDateTimeInTimezone(value, _timezone ?? 'UTC') ??
        DateTime.tryParse(value)?.toUtc() ??
        DateTime.utc(1970);
  }
}

class _TimelineDayHeader extends StatelessWidget {
  const _TimelineDayHeader({required this.item, required this.timezone});

  final TimelineReadItem item;
  final String? timezone;

  @override
  Widget build(BuildContext context) {
    final occurred = jiyiDateTimeInTimezone(item.occurredAt, timezone ?? 'UTC') ??
        DateTime.tryParse(item.occurredAt)?.toUtc() ??
        DateTime.utc(1970);
    final date = '${occurred.year}年${occurred.month}月';
    return Padding(
      key: ValueKey('timeline-month-${occurred.year}-${occurred.month}'),
      padding: const EdgeInsets.only(
        top: JiYiSpacing.sm,
        bottom: JiYiSpacing.xs,
      ),
      child: Row(
        children: [
          Icon(
            Icons.calendar_today_outlined,
            size: 16,
            color: Theme.of(context).colorScheme.primary,
          ),
          const SizedBox(width: JiYiSpacing.xs),
          Text(
            date,
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
          ),
        ],
      ),
    );
  }
}

class _TimelineEntry extends StatelessWidget {
  const _TimelineEntry({
    required this.api,
    required this.item,
    required this.timezone,
    required this.isLast,
    required this.onTap,
    this.mediaCache,
    this.photoThumbnailBuilder,
  });

  final JiYiApiClient api;
  final TimelineReadItem item;
  final String? timezone;
  final LocalMediaCache? mediaCache;
  final LocalMediaThumbnailBuilder? photoThumbnailBuilder;
  final bool isLast;
  final VoidCallback onTap;

  Widget _photoThumbnail(
    BuildContext context, {
    double width = 72,
    double height = 72,
  }) {
    final mediaId = item.mediaId!;
    final builder = photoThumbnailBuilder;
    if (builder != null) {
      return SizedBox(
        key: ValueKey('timeline-photo-${item.id}'),
        width: width,
        height: height,
        child: KeyedSubtree(
          key: ValueKey('local-media-ready-$mediaId'),
          child: builder(context, mediaId, BoxFit.cover),
        ),
      );
    }
    return LocalMediaThumbnail(
      key: ValueKey('timeline-photo-${item.id}'),
      api: api,
      mediaId: mediaId,
      cache: mediaCache,
      width: width,
      height: height,
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final occurred = jiyiDateTimeInTimezone(item.occurredAt, timezone ?? 'UTC') ??
        DateTime.tryParse(item.occurredAt)?.toUtc() ??
        DateTime.utc(1970);
    final day = '${occurred.month}月${occurred.day}日';
    String two(int value) => value.toString().padLeft(2, '0');
    final time = '${two(occurred.hour)}:${two(occurred.minute)}';
    final title = item.isMemory
        ? (item.title ?? _timelineMemoryTypeLabel(item.memoryType))
        : (item.placeName ?? '一次到访');
    final message = item.isMemory
        ? (item.content ?? '一段记忆')
        : (item.visitFinalized == true ? '已形成足迹' : '到访仍在更新');
    final icon = item.isMemory
        ? _timelineMemoryIcon(item.memoryType)
        : Icons.place_outlined;

    return Semantics(
      key: ValueKey('timeline-entry-${item.kind}-${item.id}'),
      button: true,
      label: '$day $time $title',
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          borderRadius: BorderRadius.circular(JiYiRadius.card),
          onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.only(bottom: JiYiSpacing.sm),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 70,
                child: Padding(
                  padding: const EdgeInsets.only(top: JiYiSpacing.md),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text(
                        day,
                        style: theme.textTheme.labelLarge?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: JiYiSpacing.xxs),
                      Text(
                        time,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: JiYiSpacing.sm),
              SizedBox(
                width: 20,
                child: Column(
                  children: [
                    const SizedBox(height: JiYiSpacing.md),
                    Container(
                      width: 12,
                      height: 12,
                      decoration: BoxDecoration(
                        color: theme.colorScheme.primary,
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: theme.colorScheme.surface,
                          width: 3,
                        ),
                      ),
                    ),
                    if (!isLast)
                      Container(
                        width: 2,
                        height: 94,
                        color: theme.colorScheme.outlineVariant,
                      ),
                  ],
                ),
              ),
              const SizedBox(width: JiYiSpacing.sm),
              Expanded(
                child: V3SurfaceCard(
                  padding: const EdgeInsets.all(JiYiSpacing.cardPadding),
                  borderColor: Colors.transparent,
                  borderRadius: BorderRadius.circular(JiYiRadius.card),
                  elevation: 1,
                  shadowColor: const Color(0x1A152D4B),
                  semanticLabel: '$day $time $title',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (item.memoryType == 'PHOTO' && item.mediaId != null) ...[
                        ClipRRect(
                          borderRadius: BorderRadius.circular(JiYiRadius.control),
                          child: _photoThumbnail(
                            context,
                            width: double.infinity,
                            height: 156,
                          ),
                        ),
                        const SizedBox(height: JiYiSpacing.sm),
                      ] else ...[
                        Row(
                          children: [
                            Icon(icon, color: theme.colorScheme.primary),
                            const SizedBox(width: JiYiSpacing.sm),
                            Expanded(
                              child: Text(
                                title,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: theme.textTheme.titleMedium?.copyWith(
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: JiYiSpacing.xs),
                      ],
                      if (item.memoryType == 'PHOTO' && item.mediaId != null)
                        Text(
                          title,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      const SizedBox(height: JiYiSpacing.xxs),
                      Wrap(
                        spacing: JiYiSpacing.xs,
                        runSpacing: JiYiSpacing.xxs,
                        children: [
                          Text(
                            '$day · $time',
                            style: theme.textTheme.bodyMedium?.copyWith(
                              color: theme.colorScheme.onSurfaceVariant,
                            ),
                          ),
                          if (item.placeName != null)
                            Chip(
                              avatar: const Icon(Icons.place_outlined, size: 18),
                              label: Text(item.placeName!),
                              visualDensity: VisualDensity.compact,
                            ),
                        ],
                      ),
                      const SizedBox(height: JiYiSpacing.xs),
                      Text(
                        message,
                        maxLines: 4,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.bodyLarge?.copyWith(height: 1.45),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    ),
    );
  }
}

String _timelineMemoryTypeLabel(String? value) => switch (value) {
      'NOTE' => '文字记忆',
      'VOICE' => '语音记忆',
      'PHOTO' => '照片记忆',
      'PLACE' => '地点记忆',
      'OBJECT_LOCATION' => '物品位置',
      'REMINDER' => '提醒',
      'EVENT' => '事件记录',
      _ => '一段记忆',
    };

IconData _timelineMemoryIcon(String? value) => switch (value) {
      'VOICE' => Icons.mic_none_outlined,
      'PHOTO' => Icons.photo_outlined,
      'PLACE' => Icons.place_outlined,
      'OBJECT_LOCATION' => Icons.inventory_2_outlined,
      _ => Icons.auto_stories_outlined,
    };

class CapturePage extends StatefulWidget {
  const CapturePage({
    super.key,
    required this.api,
    required this.offlineQueue,
    this.sync,
    this.syncGeneration = 0,
    this.onQueueChanged,
    this.onAuthoritativeTextMemorySaved,
    this.mediaCache,
    this.elderMode = false,
  });

  final JiYiApiClient api;
  final OfflineQueueStore offlineQueue;
  final OfflineSyncCoordinator? sync;
  final int syncGeneration;
  final VoidCallback? onQueueChanged;
  final LocalMediaCache? mediaCache;
  final bool elderMode;
  final void Function(String memoryId, String querySeed)?
      onAuthoritativeTextMemorySaved;

  @override
  State<CapturePage> createState() => _CapturePageState();
}

class _CapturePageState extends State<CapturePage> {
  final titleController = TextEditingController();
  final contentController = TextEditingController();
  final objectController = TextEditingController();
  final locationController = TextEditingController();
  bool loading = false;
  String? result;
  int offlinePendingCount = 0;
  bool privacyPaused = false;

  late final OfflineSyncCoordinator _sync =
      widget.sync ?? OfflineSyncCoordinator(api: widget.api, store: widget.offlineQueue);

  @override
  void initState() {
    super.initState();
    unawaited(_refreshOfflinePendingCount());
    if (widget.elderMode) unawaited(_refreshPrivacyPause());
  }

  @override
  void didUpdateWidget(covariant CapturePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.syncGeneration != widget.syncGeneration) {
      unawaited(_refreshOfflinePendingCount());
    }
    if (oldWidget.elderMode != widget.elderMode && widget.elderMode) {
      unawaited(_refreshPrivacyPause());
    }
  }

  @override
  void dispose() {
    titleController.dispose();
    contentController.dispose();
    objectController.dispose();
    locationController.dispose();
    super.dispose();
  }

  // [人工注释][S1-015] 本地队列只能使用当前认证响应里的真实 user_id；缺失身份时拒绝访问，避免无归属或跨账号记录。
  String get _ownerUserId {
    final userId = widget.api.authenticatedUserId;
    if (userId == null || userId.trim().isEmpty) {
      throw StateError('Authenticated user ID is required for offline storage');
    }
    return userId;
  }

  // [人工注释][S1-016] 待发送数量按当前 user_id 直接来自 SQLite；重启后仍能恢复，同时不暴露同机其他账号记录。
  Future<void> _refreshPrivacyPause() async {
    final sessionVersion = widget.api.sessionVersion;
    final owner = widget.api.authenticatedUserId;
    try {
      final status = await widget.api.getPrivacyStatus();
      if (!mounted ||
          widget.api.sessionVersion != sessionVersion ||
          widget.api.authenticatedUserId != owner) {
        return;
      }
      setState(() => privacyPaused = status['recording_paused'] == true);
    } catch (_) {
      if (mounted &&
          widget.api.sessionVersion == sessionVersion &&
          widget.api.authenticatedUserId == owner) {
        setState(() => privacyPaused = false);
      }
    }
  }

  Future<void> _refreshOfflinePendingCount() async {
    try {
      final count = await widget.offlineQueue.countAwaitingDelivery(
        _ownerUserId,
      );
      if (mounted) setState(() => offlinePendingCount = count);
    } catch (_) {
      // [人工注释][S1-016] 计数展示失败不能把真实录入流程伪装成功；保存动作仍会单独报告 SQLite 写入结果。
    }
  }

  Future<OfflineQueueItem> _flushQueued(OfflineQueueItem queued) async {
    await _sync.flush(_ownerUserId);
    final current = await widget.offlineQueue.findByClientUuid(
      _ownerUserId,
      queued.clientUuid,
    );
    if (current == null) {
      throw StateError('Offline queue item disappeared after flush');
    }
    widget.onQueueChanged?.call();
    await _refreshOfflinePendingCount();
    return current;
  }

  Future<void> saveTextMemory() async {
    final content = contentController.text.trim();
    if (content.isEmpty) return;
    final title = titleController.text.trim();
    // [人工注释][S1-026] 后端普通检索当前只匹配 Memory.content，不匹配 title。
    // 因此 Aha 自动查询必须来自真实正文；同时保持在 Query API 2000 字上限以内，
    // 并按 Unicode code points 截断，避免切坏 surrogate pair。
    final querySeed = String.fromCharCodes(content.runes.take(512));
    setState(() {
      loading = true;
      result = null;
    });
    try {
      // 首次点击时先冻结发生时间并持久化 outbox；第一次在线发送和以后所有重试
      // 都复用同一 client UUID 与 occurred_at。
      final queued = await widget.offlineQueue.enqueueTextMemory(
        ownerUserId: _ownerUserId,
        title: title,
        content: content,
      );
      final current = await _flushQueued(queued);
      if (current.status == OfflineQueueStatus.completed) {
        titleController.clear();
        contentController.clear();
        setState(() => result = '✓ 已记住');
        // Onboarding may advance only after the outbox has received an authoritative
        // server resource id. Local-only queued data cannot be queried yet.
        widget.onAuthoritativeTextMemorySaved?.call(
          current.serverResourceId!,
          querySeed,
        );
      } else if (current.status == OfflineQueueStatus.failed && current.retryable) {
        titleController.clear();
        contentController.clear();
        setState(() => result = '✓ 已保存到本机，联网后会自动重试');
      } else {
        setState(() => result = '操作失败：${current.lastError ?? '同步失败'}');
      }
    } catch (_) {
      if (mounted) setState(() => result = '操作失败：本地保存或同步失败');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> saveObjectLocation() async {
    final objectName = objectController.text.trim();
    final locationText = locationController.text.trim();
    if (objectName.isEmpty || locationText.isEmpty) return;
    setState(() {
      loading = true;
      result = null;
    });
    try {
      // recorded_at 在 enqueue 时冻结，避免延迟同步跨过 UNKNOWN watermark 后
      // 把旧位置误当成“现在才发生”的新位置。
      final queued = await widget.offlineQueue.enqueueObjectLocation(
        ownerUserId: _ownerUserId,
        objectName: objectName,
        locationText: locationText,
      );
      final current = await _flushQueued(queued);
      if (current.status == OfflineQueueStatus.completed) {
        objectController.clear();
        locationController.clear();
        setState(() => result = '✓ 已记录当前位置');
      } else if (current.status == OfflineQueueStatus.failed && current.retryable) {
        objectController.clear();
        locationController.clear();
        setState(() => result = '✓ 位置已保存到本机，联网后会自动重试');
      } else {
        setState(() => result = '操作失败：${current.lastError ?? '同步失败'}');
      }
    } catch (_) {
      if (mounted) setState(() => result = '操作失败：本地保存或同步失败');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> syncNow() async {
    setState(() {
      loading = true;
      result = null;
    });
    try {
      final report = await _sync.flush(_ownerUserId);
      await _refreshOfflinePendingCount();
      widget.onQueueChanged?.call();
      if (mounted) {
        setState(
          () => result =
              '同步完成：成功 ${report.completed}，待重试 ${report.retryableFailures}，需处理 ${report.blockedFailures}',
        );
      }
    } catch (_) {
      if (mounted) setState(() => result = '同步暂时无法完成');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> markObjectStale() async {
    if (objectController.text.trim().isEmpty) return;
    await _run(() async {
      // [人工注释][S1-011] “已经不在那里”必须由服务端把 CURRENT 改成 STALE，
      // 客户端不能只清空输入框或本地隐藏答案。
      await widget.api.markObjectLocationStale(objectController.text);
      locationController.clear();
      return '✓ 已标记 ${objectController.text.trim()} 已经不在原位置';
    });
  }

  Future<void> _run(Future<String> Function() action) async {
    setState(() {
      loading = true;
      result = null;
    });
    try {
      final message = await action();
      setState(() => result = message);
    } on ApiException catch (exc) {
      setState(() => result = '操作失败：${exc.message}');
    } catch (_) {
      setState(() => result = '操作失败：无法连接服务器');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final visibleResult = result == null
        ? null
        : _visibleCaptureResult(result!);
    final resultKind = result == null ? null : _captureStatusKind(result!);
    return JiYiPageFrame(
      title: widget.elderMode ? '帮我记一下' : '记一下',
      subtitle: widget.elderMode
          ? '先用语音说下来；你也可以选择打字或拍照。'
          : '把重要的内容或物品位置清楚地记下来。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (offlinePendingCount > 0) ...[
            // 这里只展示当前账号 SQLite 已持久化的待发送事实；不新增手动同步或暗示已经上传。
            JiYiStatusBanner(
              kind: JiYiStatusKind.warning,
              title: '本机待发送',
              message: '有 $offlinePendingCount 条记录已安全保存在本机，待联网后发送。',
            ),
            const SizedBox(height: JiYiSpacing.xs),
            OutlinedButton.icon(
              onPressed: loading ? null : syncNow,
              icon: const Icon(Icons.sync),
              label: const Text('立即同步可重试记录'),
            ),
            const SizedBox(height: JiYiSpacing.md),
          ],
          if (widget.elderMode) ...[
            if (privacyPaused) ...[
              const JiYiStatusBanner(
                kind: JiYiStatusKind.info,
                title: '自动记录已暂停',
                message: '自动记录已暂停；你主动记下的内容仍可以保存。',
              ),
              const SizedBox(height: JiYiSpacing.md),
            ],
            UnifiedMediaCaptureSection(
              api: widget.api,
              mediaCache: widget.mediaCache,
              elderMode: true,
            ),
            const SizedBox(height: JiYiSpacing.md),
          ],
          if (!widget.elderMode) ...[
            const JiYiSectionHeader(
              title: '先留住声音和画面',
              subtitle: '只在你主动操作时录音、拍照或选择图片。',
            ),
            const SizedBox(height: JiYiSpacing.sm),
            UnifiedMediaCaptureSection(
              api: widget.api,
              mediaCache: widget.mediaCache,
            ),
            const SizedBox(height: JiYiSpacing.xl),
            const JiYiSectionHeader(
              title: '也可以写下来',
              subtitle: '一句话、一个物品位置，都可以成为以后找得回来的记录。',
            ),
            const SizedBox(height: JiYiSpacing.sm),
          ],
          JiYiSectionCard(
            leading: Icon(
              Icons.edit_note_outlined,
              color: theme.colorScheme.primary,
            ),
            title: widget.elderMode ? '我想打字记' : '写一句',
            subtitle: widget.elderMode
                ? '如果不方便说，也可以自己打字。'
                : '适合记录临时安排、承诺、重要提醒或一段想留下的话。',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  key: const ValueKey('capture-text-title'),
                  controller: titleController,
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(
                    labelText: '标题（可选）',
                    prefixIcon: Icon(Icons.title_outlined),
                  ),
                ),
                const SizedBox(height: JiYiSpacing.sm),
                TextField(
                  key: const ValueKey('capture-text-content'),
                  controller: contentController,
                  minLines: 3,
                  maxLines: 6,
                  decoration: const InputDecoration(
                    labelText: '内容',
                    hintText: '例如：老张周五下午来公司取合同。',
                    alignLabelWithHint: true,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.md),
                FilledButton.icon(
                  key: const ValueKey('capture-text-submit'),
                  onPressed: loading ? null : saveTextMemory,
                  icon: loading
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.bookmark_add_outlined),
                  label: const Text('帮我记住'),
                ),
              ],
            ),
          ),
          const SizedBox(height: JiYiSpacing.md),
          JiYiSectionCard(
            leading: Icon(
              Icons.inventory_2_outlined,
              color: theme.colorScheme.primary,
            ),
            title: '东西在哪',
            subtitle: '记录物品的当前位置；如果已经移动，可以明确标记原位置失效。',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  controller: objectController,
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(
                    labelText: '物品',
                    hintText: '例如：护照',
                    prefixIcon: Icon(Icons.inventory_2_outlined),
                  ),
                ),
                const SizedBox(height: JiYiSpacing.sm),
                TextField(
                  controller: locationController,
                  textInputAction: TextInputAction.done,
                  decoration: const InputDecoration(
                    labelText: '位置',
                    hintText: '例如：书房左侧柜子第二层',
                    prefixIcon: Icon(Icons.place_outlined),
                  ),
                ),
                const SizedBox(height: JiYiSpacing.md),
                FilledButton.tonalIcon(
                  onPressed: loading ? null : saveObjectLocation,
                  icon: const Icon(Icons.add_location_alt_outlined),
                  label: const Text('记录当前位置'),
                ),
                const SizedBox(height: JiYiSpacing.xs),
                OutlinedButton.icon(
                  onPressed: loading ? null : markObjectStale,
                  icon: const Icon(Icons.location_off_outlined),
                  label: const Text('已经不在那里'),
                ),
              ],
            ),
          ),
          if (visibleResult != null && resultKind != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            // 原始 result 仍保留给现有行为测试与状态机；展示层只隐藏无产品价值的内部 id/clientUuid 后缀。
            JiYiStatusBanner(kind: resultKind, message: visibleResult),
          ],
          const SizedBox(height: JiYiSpacing.md),
        ],
      ),
    );
  }
}

// Capture 状态样式只根据现有结果文案分类，不改变任何成功/失败/离线判断来源。
JiYiStatusKind _captureStatusKind(String value) {
  if (value.startsWith('操作失败：')) return JiYiStatusKind.error;
  if (value.contains('已保存到本机')) return JiYiStatusKind.warning;
  return JiYiStatusKind.success;
}

// 内部 UUID/Memory id 继续存在于业务返回值中，但不直接暴露给客户；错误文案与可理解的位置结果原样保留。
String _visibleCaptureResult(String value) {
  if (!value.startsWith('✓')) return value;
  final separator = value.lastIndexOf(' · ');
  if (separator <= 0) return value;
  return value.substring(0, separator);
}

String _evidenceSourceLabel(String? sourceType) {
  const labels = <String, String>{
    'USER_TEXT': '用户文字记录',
    'USER_VOICE': '用户语音记录',
    'USER_PHOTO': '用户照片记录',
    'GPS': 'GPS 位置证据',
    'PHOTO_EXIF': '照片位置信息',
    'SYSTEM_PLACE': '系统地点识别',
    'AI_INFERENCE': 'AI 推测',
  };
  return labels[sourceType] ?? sourceType ?? '未知来源';
}

class _MemoryEditDraft {
  const _MemoryEditDraft({required this.title, required this.content});

  final String? title;
  final String content;
}

class _MemoryEditDialog extends StatefulWidget {
  const _MemoryEditDialog({required this.title, required this.content});

  final String? title;
  final String content;

  @override
  State<_MemoryEditDialog> createState() => _MemoryEditDialogState();
}

class _MemoryEditDialogState extends State<_MemoryEditDialog> {
  late final TextEditingController titleController =
      TextEditingController(text: widget.title ?? '');
  late final TextEditingController contentController =
      TextEditingController(text: widget.content);
  String? validationError;

  @override
  void dispose() {
    titleController.dispose();
    contentController.dispose();
    super.dispose();
  }

  void save() {
    final content = contentController.text.trim();
    if (content.isEmpty) {
      setState(() => validationError = '内容不能为空');
      return;
    }
    final title = titleController.text.trim();
    Navigator.pop(
      context,
      _MemoryEditDraft(
        title: title.isEmpty ? null : title,
        content: content,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('编辑这条记忆'),
      content: SizedBox(
        width: 520,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              key: const ValueKey('memory-edit-title'),
              controller: titleController,
              maxLength: 240,
              decoration: const InputDecoration(labelText: '标题（可选）'),
            ),
            TextField(
              key: const ValueKey('memory-edit-content'),
              controller: contentController,
              minLines: 4,
              maxLines: 8,
              maxLength: 20000,
              decoration: InputDecoration(
                labelText: '内容',
                alignLabelWithHint: true,
                errorText: validationError,
              ),
            ),
            const SizedBox(height: JiYiSpacing.xs),
            Text(
              '编辑会保留原始记录；正文修改会标记为你的后续修正。',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          key: const ValueKey('memory-edit-save'),
          onPressed: save,
          child: const Text('保存修改'),
        ),
      ],
    );
  }
}

String _queryCertaintyLabel(String value) => switch (value) {
      'confirmed' => '明确记录',
      'evidence' => '有相关记录',
      _ => '没有足够记录',
    };

String _queryIntentLabel(String value) => switch (value) {
      'FIND_OBJECT' => '查找物品',
      'FIND_EVENT' => '回忆当天发生的事',
      'RECALL_EVENT' => '回忆一件事',
      'FIND_PLACE' => '查找地点',
      'FIND_PERSON' => '查找人物',
      'DATE_FOOTPRINT_QUERY' => '按日期看足迹',
      _ => '查找记忆',
    };

String _queryFootprintClock(String serverLocalIso) {
  final match = RegExp(r'T(\d{2}):(\d{2})').firstMatch(serverLocalIso);
  if (match == null) return '时间未知';
  return '${match.group(1)}:${match.group(2)}';
}

String _queryFootprintTimeRange(Map<String, dynamic> visit) {
  final start = _queryFootprintClock(visit['arrived_at_local']?.toString() ?? '');
  final endRaw = visit['left_at_local'];
  if (endRaw == null) return '$start 起';
  final end = _queryFootprintClock(endRaw.toString());
  return '$start - $end';
}

String _queryEvidenceKindLabel(String value) => switch (value) {
      'OBJECT_LOCATION' => '物品位置',
      'MEMORY' => '记忆',
      'PLACE' => '地点记录',
      'PHOTO' => '照片记录',
      'VOICE' => '语音记录',
      _ => '相关记录',
    };

class MemoryQueryPage extends StatefulWidget {
  const MemoryQueryPage({
    super.key,
    required this.api,
    this.elderMode = false,
    this.onCapture,
    this.initialQuestion,
    this.requiredEvidenceMemoryId,
    this.onTrustedEvidenceShown,
    this.mediaCache,
    this.amapPrivacyConsent,
    this.notificationClient,
  });

  final JiYiApiClient api;
  final LocalMediaCache? mediaCache;
  final bool elderMode;
  final VoidCallback? onCapture;
  final String? initialQuestion;
  final String? requiredEvidenceMemoryId;
  final VoidCallback? onTrustedEvidenceShown;
  final AmapPrivacyConsentAuthority? amapPrivacyConsent;
  final NotificationClientService? notificationClient;

  @override
  State<MemoryQueryPage> createState() => _MemoryQueryPageState();
}

class _MemoryQueryPageState extends State<MemoryQueryPage> {
  final controller = TextEditingController();
  Map<String, dynamic>? result;
  String? error;
  String? actionMessage;
  String? submittedQuestion;
  bool loading = false;
  bool _qualifyingTrustedEvidenceAvailable = false;
  bool _trustedEvidenceShownForCurrentQuery = false;
  int _queryGeneration = 0;
  late int _observedSessionVersion;
  String? _observedOwner;
  late final AmapPrivacyConsentAuthority _amapPrivacyConsent;
  bool _mapPrivacyAccepted = false;

  @override
  void initState() {
    super.initState();
    _amapPrivacyConsent =
        widget.amapPrivacyConsent ?? AmapPrivacyConsentStore();
    _loadMapPrivacy();
    _observedSessionVersion = widget.api.sessionVersion;
    _observedOwner = widget.api.authenticatedUserId;
    final initial = widget.initialQuestion?.trim();
    if (initial != null && initial.isNotEmpty) {
      controller.text = initial;
    }
  }

  @override
  void didUpdateWidget(covariant MemoryQueryPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    final currentSessionVersion = widget.api.sessionVersion;
    final currentOwner = widget.api.authenticatedUserId;
    if (_observedSessionVersion != currentSessionVersion ||
        _observedOwner != currentOwner) {
      _queryGeneration += 1;
      result = null;
      error = null;
      actionMessage = null;
      submittedQuestion = null;
      loading = false;
    }
    _observedSessionVersion = currentSessionVersion;
    _observedOwner = currentOwner;

    final next = widget.initialQuestion?.trim();
    if (oldWidget.initialQuestion != widget.initialQuestion &&
        controller.text.trim().isEmpty &&
        next != null &&
        next.isNotEmpty) {
      controller.text = next;
    }
  }

  Future<void> _loadMapPrivacy() async {
    try {
      final accepted = await _amapPrivacyConsent.readAccepted();
      if (mounted) setState(() => _mapPrivacyAccepted = accepted);
    } catch (_) {
      if (mounted) setState(() => _mapPrivacyAccepted = false);
    }
  }

  Future<void> _acceptMapPrivacy() async {
    final accepted =
        await requestAmapPrivacyConsent(context, _amapPrivacyConsent);
    if (mounted && accepted) setState(() => _mapPrivacyAccepted = true);
  }

  @override
  void dispose() {
    _queryGeneration += 1;
    controller.dispose();
    super.dispose();
  }

  Future<void> query() async {
    if (loading) return;
    final submitted = controller.text.trim();
    if (submitted.isEmpty) {
      setState(() => error = widget.elderMode ? '请告诉我你要找什么' : '请输入你想回忆的问题');
      return;
    }

    final generation = ++_queryGeneration;
    final sessionVersion = widget.api.sessionVersion;
    final owner = widget.api.authenticatedUserId;
    setState(() {
      loading = true;
      error = null;
      actionMessage = null;
      result = null;
      submittedQuestion = submitted;
      _qualifyingTrustedEvidenceAvailable = false;
      _trustedEvidenceShownForCurrentQuery = false;
    });
    bool isCurrent() =>
        mounted &&
        generation == _queryGeneration &&
        sessionVersion == widget.api.sessionVersion &&
        owner == widget.api.authenticatedUserId;
    try {
      final response = await widget.api.queryMemory(submitted);
      if (!isCurrent()) return;
      final evidence = response['evidence'];
      final memoryIds = response['memory_ids'];
      final requiredMemoryId = widget.requiredEvidenceMemoryId?.trim();
      final containsRequiredMemory = requiredMemoryId == null ||
          requiredMemoryId.isEmpty ||
          (memoryIds is List<dynamic> &&
              memoryIds.any((value) => value.toString() == requiredMemoryId));
      final qualifyingTrustedEvidenceAvailable = response['can_answer'] == true &&
          evidence is List<dynamic> &&
          evidence.isNotEmpty &&
          containsRequiredMemory;
      setState(() {
        result = response;
        _qualifyingTrustedEvidenceAvailable = qualifyingTrustedEvidenceAvailable;
        _trustedEvidenceShownForCurrentQuery = false;
      });
    } on ApiException catch (exc) {
      if (!isCurrent()) return;
      setState(() => error = exc.message);
    } on ProtocolException {
      if (!isCurrent()) return;
      setState(() => error = '查询结果无法验证，请稍后重试');
    } catch (_) {
      if (!isCurrent()) return;
      setState(() => error = '暂时无法连接服务器');
    } finally {
      if (isCurrent()) {
        setState(() => loading = false);
      }
    }
  }

  Future<void> editFirstMemory() async {
    final ids = result?['memory_ids'] as List<dynamic>? ?? const [];
    if (ids.isEmpty) return;
    final memoryId = ids.first.toString();

    setState(() {
      loading = true;
      error = null;
      actionMessage = null;
    });
    late final Map<String, dynamic> memory;
    try {
      memory = await widget.api.getMemory(memoryId);
    } on ApiException catch (exc) {
      if (mounted) setState(() => error = exc.message);
      return;
    } catch (_) {
      if (mounted) setState(() => error = '暂时无法读取这条记忆');
      return;
    } finally {
      if (mounted) setState(() => loading = false);
    }
    if (!mounted) return;
    final revision = memory['edit_revision'];
    if (revision is! int || revision < 0) {
      setState(() => error = '这条记忆刚刚发生了变化，请重新查询后再试');
      return;
    }

    final draft = await showDialog<_MemoryEditDraft>(
      context: context,
      builder: (context) => _MemoryEditDialog(
        title: memory['title']?.toString(),
        content: memory['content']?.toString() ?? '',
      ),
    );
    if (draft == null || !mounted) return;

    setState(() {
      loading = true;
      error = null;
      actionMessage = null;
    });
    try {
      await widget.api.updateMemory(
        memoryId,
        expectedRevision: revision,
        title: draft.title,
        content: draft.content,
      );
      // PATCH 成功后重新经过 query/Evidence gate；客户端不拼接“编辑后的可信答案”。
      final refreshed = await widget.api.queryMemory(controller.text);
      if (!mounted) return;
      setState(() {
        result = refreshed;
        actionMessage = '✓ 记忆已更新，原始记录仍然保留';
      });
    } on ApiException catch (exc) {
      if (!mounted) return;
      final message =
          exc.statusCode == 409 && exc.message == 'MEMORY_EDIT_REVISION_CONFLICT'
              ? '这条记忆已经在其他地方更新，请重新查询后再编辑'
              : exc.message;
      setState(() => error = message);
    } catch (_) {
      if (mounted) setState(() => error = '暂时无法保存修改');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> openFirstMemoryDetail() async {
    final ids = result?['memory_ids'] as List<dynamic>? ?? const [];
    if (ids.isEmpty || !mounted) return;
    await JiYiNavigator.pushDetail<bool>(
      context,
      builder: (_) => MemoryDetailPage(
        api: widget.api,
        memoryId: ids.first.toString(),
        mediaCache: widget.mediaCache,
        amapPrivacyConsent: _amapPrivacyConsent,
      ),
    );
  }

  Future<void> createReminderForFirstMemory() async {
    final ids = result?['memory_ids'] as List<dynamic>? ?? const [];
    if (ids.isEmpty) return;

    setState(() {
      loading = true;
      error = null;
      actionMessage = null;
    });
    try {
      // [人工注释][S1-025] Reminder 的表单、稳定幂等键与 response-loss 重试都封装在独立模块；
      // Stage1 shared shell 只负责把当前真实 memory_id 接到该流程。Onboarding 的 query/Evidence Aha 状态不在这里改写。
      final message = await showMemoryReminderCreateFlow(
        context: context,
        api: widget.api,
        memoryId: ids.first.toString(),
      );
      if (!mounted || message == null) return;
      setState(() => actionMessage = message);
      final notifications = widget.notificationClient;
      if (notifications != null &&
          notifications.permission == NotificationPermissionState.notDetermined) {
        unawaited(notifications.requestPermissionAndRegister());
      }
    } on ApiException catch (exc) {
      if (mounted) setState(() => error = exc.message);
    } catch (_) {
      if (mounted) setState(() => error = '暂时无法打开提醒创建流程');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> deleteFirstMemory() async {
    final ids = result?['memory_ids'] as List<dynamic>? ?? const [];
    if (ids.isEmpty) {
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这条记忆？'),
        content: const Text('删除后，这条记忆以及依赖它的当前位置答案都不能再被找回。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          // 删除语义不变，只把确认动作明确显示为危险操作，避免与普通主按钮混淆。
          FilledButton.icon(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
            onPressed: () => Navigator.pop(context, true),
            icon: const Icon(Icons.delete_outline),
            label: const Text('确认删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) {
      return;
    }

    final memoryId = ids.first.toString();
    final owner = widget.api.authenticatedUserId;
    String? mediaId;
    setState(() => loading = true);
    try {
      // Resolve the server-owned media identity before deletion so every
      // supported delete surface can revoke local presentation bytes too.
      // Failure to read the optional media projection must not block deletion.
      try {
        final memory = await widget.api.getMemory(memoryId);
        final metadata = memory['metadata_json'];
        final candidate = metadata is Map<String, dynamic>
            ? metadata['media_id']
            : null;
        if (candidate is String && candidate.trim().isNotEmpty) {
          mediaId = candidate.trim();
        }
      } catch (_) {
        mediaId = null;
      }

      // [人工注释][S1-019] 只有服务端 DELETE 成功后才清空当前答案，
      // 这样“删除”才是真正影响后续检索的业务操作。
      await widget.api.deleteMemory(memoryId);
      final cache = widget.mediaCache;
      if (owner != null && cache != null) {
        if (mediaId != null) {
          await cache.invalidateMedia(
            ownerUserId: owner,
            mediaId: mediaId,
          );
        } else {
          // Canonical delete succeeded but the pre-delete projection could not
          // prove the backing media identity. Prefer a broader owner purge over
          // retaining an unknown deleted object as local presentation authority.
          await cache.purgeOwner(owner);
        }
      }
      setState(() {
        result = null;
        actionMessage = '✓ 这条记忆已删除，后续查询不会再使用它';
      });
    } on ApiException catch (exc) {
      setState(() => error = exc.message);
    } finally {
      if (mounted) {
        setState(() => loading = false);
      }
    }
  }

  Widget _buildMemoryV3(BuildContext context) {
    final theme = Theme.of(context);
    final evidence = (result?['evidence'] as List<dynamic>? ?? const [])
        .where((item) =>
            item is Map<String, dynamic> &&
            item['source_type']?.toString() != 'AI_INFERENCE')
        .toList(growable: false);
    final memoryIds = (result?['memory_ids'] as List<dynamic>? ?? const []);
    final canAnswer = result?['can_answer'] == true;
    final answer = result?['answer']?.toString() ?? '';
    final certainty = result?['certainty']?.toString() ?? 'unknown';
    final intent = result?['intent']?.toString() ?? '';
    final dayFootprintRaw = result?['day_footprint'];
    final dayFootprint =
        dayFootprintRaw is Map<String, dynamic> ? dayFootprintRaw : null;
    final footprintVisits =
        (dayFootprint?['visits'] as List<dynamic>? ?? const <dynamic>[])
            .whereType<Map<String, dynamic>>()
            .toList(growable: false);
    final footprintDay = dayFootprint?['day']?.toString();
    FootprintDay? canonicalFootprint;
    if (dayFootprint != null) {
      try {
        canonicalFootprint = FootprintDay.fromJson(dayFootprint);
      } on FormatException {
        canonicalFootprint = null;
      }
    }
    final certaintyLabel = _queryCertaintyLabel(certainty);
    final intentLabel = _queryIntentLabel(intent);
    final canEditFirstMemory = memoryIds.isNotEmpty && intent != 'FIND_OBJECT';
    final navy = JiYiTodayVisuals.navy;
    final secondary = JiYiTodayVisuals.secondaryText;

    Widget surface(
      Widget child, {
      EdgeInsetsGeometry padding = const EdgeInsets.all(16),
    }) {
      return DecoratedBox(
        decoration: BoxDecoration(
          color: JiYiTodayVisuals.card,
          borderRadius: BorderRadius.circular(20),
          boxShadow: const [
            BoxShadow(
              color: JiYiTodayVisuals.cardShadow,
              blurRadius: 10,
              offset: Offset(0, 2),
            ),
          ],
        ),
        child: Padding(
          padding: padding,
          child: Material(
            type: MaterialType.transparency,
            child: child,
          ),
        ),
      );
    }

    Widget sectionHeader(
      String title, {
      VoidCallback? onAction,
      String? actionTooltip,
    }) {
      return Row(
        children: [
          Expanded(
            child: Text(
              title,
              style: TextStyle(
                color: navy,
                fontSize: 28,
                height: 1.2,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
          if (onAction != null)
            IconButton(
              key: const ValueKey('memory-timeline-open'),
              tooltip: actionTooltip,
              onPressed: onAction,
              icon: const Icon(Icons.timeline_outlined),
              color: secondary,
            ),
        ],
      );
    }

    Widget emptySurface({
      required IconData icon,
      required String title,
      required String message,
    }) {
      return surface(
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            DecoratedBox(
              decoration: const BoxDecoration(
                color: JiYiProductColors.surfaceSoft,
                shape: BoxShape.circle,
              ),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Icon(icon, color: JiYiTodayVisuals.primaryBlue),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: TextStyle(
                      color: navy,
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(message, style: TextStyle(color: secondary, height: 1.45)),
                ],
              ),
            ),
          ],
        ),
      );
    }

    Widget resultSurface() {
      final fallback = widget.elderMode
          ? '没有找到足够可靠的记录。你可以先用“帮我记一下”告诉我放在哪里。'
          : '我没有找到能够支持答案的相关记录。';
      return surface(
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  canAnswer ? Icons.auto_awesome_outlined : Icons.search_off_outlined,
                  color: canAnswer ? JiYiTodayVisuals.primaryBlue : secondary,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    canAnswer
                        ? (intent == 'DATE_FOOTPRINT_QUERY' && footprintVisits.isNotEmpty
                            ? (widget.elderMode ? '找到了这天的足迹' : '这天的足迹')
                            : (widget.elderMode ? '找到了可信记录' : '找到相关记忆'))
                        : (widget.elderMode ? '我还不知道它在哪里' : '没有足够依据'),
                    style: TextStyle(
                      color: navy,
                      fontSize: 20,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              canAnswer && answer.isNotEmpty ? answer : fallback,
              style: TextStyle(color: navy, fontSize: 18, height: 1.5),
            ),
            if (submittedQuestion != null) ...[
              const SizedBox(height: 8),
              Text('本次查找：$submittedQuestion', style: TextStyle(color: secondary)),
            ],
            const SizedBox(height: 8),
            ExpansionTile(
              key: const ValueKey('memory-query-evidence-disclosure'),
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              onExpansionChanged: (expanded) {
                if (!expanded ||
                    !_qualifyingTrustedEvidenceAvailable ||
                    _trustedEvidenceShownForCurrentQuery) {
                  return;
                }
                _trustedEvidenceShownForCurrentQuery = true;
                widget.onTrustedEvidenceShown?.call();
              },
              title: const Text('查看这次回答的依据'),
              subtitle: Text('$certaintyLabel · $intentLabel'),
              children: [
                if (evidence.isNotEmpty)
                  ...evidence.map((item) {
                    final e = item as Map<String, dynamic>;
                    final sourceLabel =
                        _evidenceSourceLabel(e['source_type']?.toString());
                    final provenance = e['provenance']?.toString();
                    final displayedSource = provenance == 'USER_EDIT'
                        ? '$sourceLabel · 用户编辑'
                        : sourceLabel;
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: JiYiEvidenceCard(
                        excerpt: e['excerpt']?.toString() ?? '',
                        source: displayedSource,
                        evidenceType: _queryEvidenceKindLabel(
                          e['kind']?.toString() ?? '',
                        ),
                        occurredAt: e['occurred_at']?.toString() ?? '时间未知',
                        confidence: '',
                      ),
                    );
                  })
                else if (footprintVisits.isNotEmpty)
                  const Align(
                    alignment: Alignment.centerLeft,
                    child: Text('这次回答依据为服务端已形成的足迹记录。'),
                  )
                else
                  const Align(
                    alignment: Alignment.centerLeft,
                    child: Text('没有可展示的参考记录，请谨慎使用这个答案。'),
                  ),
              ],
            ),
          ],
        ),
      );
    }

    final children = <Widget>[
      if (widget.elderMode)
        Padding(
          padding: const EdgeInsets.only(top: 12, bottom: 12),
          child: Text(
            '我想找东西',
            style: TextStyle(color: navy, fontSize: 30, fontWeight: FontWeight.w800),
          ),
        )
      else ...[
        const SizedBox(height: 10),
        Text(
          '记忆',
          style: TextStyle(
            color: navy,
            fontSize: 38,
            height: 1.05,
            fontWeight: FontWeight.w800,
            letterSpacing: -1,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          '从你留下的记录里找回来',
          style: TextStyle(color: secondary, fontSize: 19, height: 1.35),
        ),
        const SizedBox(height: 28),
      ],
      surface(
        TextField(
          key: const ValueKey('memory-query-input'),
          controller: controller,
          textInputAction: TextInputAction.search,
          onSubmitted: loading ? null : (_) => query(),
          decoration: InputDecoration(
            hintText: widget.elderMode ? '物品名称或问题' : '想找哪段回忆？',
            prefixIcon: Icon(Icons.search, color: secondary, size: 30),
            border: InputBorder.none,
            enabledBorder: InputBorder.none,
            focusedBorder: InputBorder.none,
            contentPadding: const EdgeInsets.symmetric(vertical: 10),
            suffixIcon: widget.elderMode
                ? null
                : IconButton(
                    key: const ValueKey('memory-query-submit'),
                    tooltip: loading ? '查找中' : '提交查询',
                    onPressed: loading ? null : query,
                    icon: loading
                        ? const SizedBox.square(
                            dimension: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.arrow_forward_rounded),
                  ),
          ),
        ),
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
      ),
      if (widget.elderMode)
        Align(
          alignment: Alignment.centerRight,
          child: TextButton.icon(
            key: const ValueKey('memory-query-submit'),
            onPressed: loading ? null : query,
            style: TextButton.styleFrom(
              minimumSize: const Size.fromHeight(56),
              padding: const EdgeInsets.symmetric(horizontal: 16),
            ),
            icon: loading
                ? const SizedBox.square(
                    dimension: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.arrow_forward_rounded, size: 18),
            label: Text(loading ? '查找中…' : '帮我找'),
          ),
        ),
      if (!widget.elderMode)
        SizedBox(
          height: 44,
          child: ListView(
            scrollDirection: Axis.horizontal,
            children: [
              _MemorySuggestionChip(
                icon: Icons.location_on_outlined,
                label: '上周去了哪里',
                color: const Color(0xFFE7F1FF),
                onPressed: () => _setQueryPrompt('上周去了哪里'),
              ),
              _MemorySuggestionChip(
                icon: Icons.photo_outlined,
                label: '和妈妈的照片',
                color: const Color(0xFFFFEDE5),
                onPressed: () => _setQueryPrompt('和妈妈的照片'),
              ),
              _MemorySuggestionChip(
                icon: Icons.calendar_month_outlined,
                label: '这个月的回忆',
                color: const Color(0xFFE8F1FF),
                onPressed: () => _setQueryPrompt('这个月的回忆'),
              ),
              _MemorySuggestionChip(
                icon: Icons.sell_outlined,
                label: '找一找物品',
                color: const Color(0xFFFFF0DE),
                onPressed: () => _setQueryPrompt('找一找物品'),
              ),
            ],
          ),
        ),
      if (result != null) ...[
        const SizedBox(height: 20),
        resultSurface(),
        if (footprintVisits.isNotEmpty) ...[
          const SizedBox(height: 16),
          if (canonicalFootprint != null && canonicalFootprint.mappableVisits.isNotEmpty) ...[
            JiYiFootprintMap(
              key: const ValueKey('memory-query-day-map'),
              visits: canonicalFootprint.visits,
              privacyAccepted: _mapPrivacyAccepted,
              selectedIndex: 0,
              onSelected: (_) {},
              interactive: true,
            ),
            if (!_mapPrivacyAccepted) ...[
              const SizedBox(height: 8),
              OutlinedButton.icon(
                key: const ValueKey('memory-query-amap-privacy-accept'),
                onPressed: _acceptMapPrivacy,
                icon: const Icon(Icons.map_outlined),
                label: const Text('同意地图服务隐私说明并启用地图'),
              ),
            ],
            const SizedBox(height: 12),
          ],
          surface(
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  footprintDay == null ? '当天足迹' : '$footprintDay 足迹',
                  style: TextStyle(color: navy, fontSize: 19, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 6),
                Text('只显示服务端已形成的地点访问记录。', style: TextStyle(color: secondary)),
                const SizedBox(height: 12),
                ...footprintVisits.map((visit) {
                  final placeName = visit['place_name']?.toString() ?? '未命名地点';
                  final range = _queryFootprintTimeRange(visit);
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.location_on_outlined),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(placeName, style: TextStyle(color: navy, fontWeight: FontWeight.w700)),
                              Text(range, style: TextStyle(color: secondary)),
                            ],
                          ),
                        ),
                      ],
                    ),
                  );
                }),
              ],
            ),
          ),
        ],
        if (memoryIds.isNotEmpty) ...[
          const SizedBox(height: 12),
          surface(
            ExpansionTile(
              initiallyExpanded: true,
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              leading: const Icon(Icons.more_horiz),
              title: const Text('进一步操作'),
              subtitle: const Text('查看、编辑、提醒或删除这条真实记忆'),
              children: [
                FilledButton.tonalIcon(
                  key: const ValueKey('memory-detail-open'),
                  onPressed: loading ? null : openFirstMemoryDetail,
                  icon: const Icon(Icons.open_in_new),
                  label: const Text('查看完整记忆'),
                ),
                const SizedBox(height: 8),
                FilledButton.tonalIcon(
                  key: const ValueKey('memory-reminder-open'),
                  onPressed: loading ? null : createReminderForFirstMemory,
                  icon: const Icon(Icons.alarm_add_outlined),
                  label: const Text('为这条记忆设置提醒'),
                ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  key: const ValueKey('open-reminder-management'),
                  onPressed: loading
                      ? null
                      : () {
                          unawaited(
                            JiYiNavigator.push<void>(
                              context,
                              builder: (_) => ReminderPage(api: widget.api),
                            ),
                          );
                        },
                  icon: const Icon(Icons.alarm_outlined),
                  label: const Text('查看提醒管理'),
                ),
                if (canEditFirstMemory) ...[
                  const SizedBox(height: 8),
                  FilledButton.tonalIcon(
                    key: const ValueKey('memory-edit-open'),
                    onPressed: loading ? null : editFirstMemory,
                    icon: const Icon(Icons.edit_outlined),
                    label: const Text('编辑最相关记忆'),
                  ),
                ],
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: theme.colorScheme.error,
                    side: BorderSide(color: theme.colorScheme.error),
                  ),
                  onPressed: loading ? null : deleteFirstMemory,
                  icon: const Icon(Icons.delete_outline),
                  label: const Text('删除最相关记忆'),
                ),
              ],
            ),
          ),
        ],
      ],
      if (!widget.elderMode) ...[
        const SizedBox(height: 34),
        sectionHeader(
          '最近记下的',
          onAction: () {
            unawaited(
              JiYiNavigator.pushDetail<void>(
                context,
                builder: (_) => TimelinePage(
                  api: widget.api,
                  mediaCache: widget.mediaCache,
                  elderMode: widget.elderMode,
                  amapPrivacyConsent: _amapPrivacyConsent,
                ),
              ),
            );
          },
          actionTooltip: '时间线',
        ),
        const SizedBox(height: 12),
        emptySurface(
          icon: Icons.auto_stories_outlined,
          title: '你的记忆会在这里出现',
          message: '当前页面只展示真实记录。先记下一段文字、语音或照片，再回来查看。',
        ),
        const SizedBox(height: 30),
        sectionHeader('重要的人'),
        const SizedBox(height: 12),
        emptySurface(
          icon: Icons.people_outline,
          title: '还没有可展示的人物记录',
          message: '人物内容需要真实的人物 authority；迹忆不会用设计图头像代替用户数据。',
        ),
      ],
      if (error != null) ...[
        const SizedBox(height: 16),
        JiYiStatusBanner(
          kind: JiYiStatusKind.error,
          title: '暂时无法查找',
          message: error!,
        ),
      ],
      if (actionMessage != null) ...[
        const SizedBox(height: 16),
        JiYiStatusBanner(kind: JiYiStatusKind.success, message: actionMessage!),
      ],
    ];

    return Stack(
      children: [
        DecoratedBox(
          decoration: const BoxDecoration(color: JiYiTodayVisuals.background),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 92),
            children: children,
          ),
        ),
        if (!widget.elderMode && widget.onCapture != null)
          Positioned(
            right: 16,
            bottom: 16,
            child: FloatingActionButton(
              key: const ValueKey('memory-capture'),
              tooltip: '记一下',
              onPressed: widget.onCapture,
              backgroundColor: JiYiTodayVisuals.primaryBlue,
              foregroundColor: Colors.white,
              shape: const CircleBorder(),
              elevation: 2,
              focusElevation: 2,
              hoverElevation: 2,
              highlightElevation: 1,
              child: const Icon(Icons.edit_outlined),
            ),
          ),
      ],
    );
  }

  void _setQueryPrompt(String prompt) {
    controller
      ..text = prompt
      ..selection = TextSelection.collapsed(offset: prompt.length);
  }

  @override
  Widget build(BuildContext context) {
    return _buildMemoryV3(context);
  }
}

class _MemorySuggestionChip extends StatelessWidget {
  const _MemorySuggestionChip({
    required this.icon,
    required this.label,
    required this.color,
    required this.onPressed,
  });

  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ActionChip(
        onPressed: onPressed,
        avatar: Icon(icon, size: 18, color: JiYiTodayVisuals.primaryBlue),
        label: Text(label),
        backgroundColor: color,
        side: BorderSide.none,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
        ),
      ),
    );
  }
}

class ProfilePage extends StatelessWidget {
  const ProfilePage({
    super.key,
    required this.api,
    this.onElderModeChanged,
    required this.onLogout,
    required this.onAccountDeleteIntentConfirmed,
    required this.onAccountDeleted,
    this.resumeAccountDeletion = false,
    this.nativeLocationController,
    this.offlineQueue,
    this.onRevalidateLocationAuthority,
    this.onStartOnboarding,
    this.amapPrivacyConsent,
    this.themeMode = ThemeMode.system,
    this.onThemeModeChanged,
  });

  final JiYiApiClient api;
  final ValueChanged<bool>? onElderModeChanged;
  final VoidCallback onLogout;
  final Future<void> Function() onAccountDeleteIntentConfirmed;
  final Future<void> Function() onAccountDeleted;
  final bool resumeAccountDeletion;
  final NativeLocationController? nativeLocationController;
  final OfflineQueueStore? offlineQueue;
  final Future<void> Function()? onRevalidateLocationAuthority;
  final VoidCallback? onStartOnboarding;
  final AmapPrivacyConsentAuthority? amapPrivacyConsent;
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode>? onThemeModeChanged;

  @override
  Widget build(BuildContext context) {
    // G5 只统一 Profile 的 loading/error/account 信息层级；资料仍完全来自 getProfile() 的真实响应。
    final theme = Theme.of(context);
    return JiYiPageFrame(
      title: '我的',
      subtitle: '管理账号信息、自动记录和隐私控制。',
      hero: const JiYiHeroHeader(
        atmospheric: true,
        eyebrow: '迹忆 · 我的',
        title: '我的迹忆',
        subtitle: '先确认记录是否正常，再管理隐私、位置和账号。',
        icon: Icons.landscape_outlined,
      ),
      child: FutureBuilder<Map<String, dynamic>>(
        future: api.getProfile(),
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const JiYiSectionCard(
              child: Padding(
                padding: EdgeInsets.symmetric(vertical: JiYiSpacing.lg),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    SizedBox.square(
                      dimension: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    SizedBox(width: JiYiSpacing.sm),
                    Text('正在读取个人资料…'),
                  ],
                ),
              ),
            );
          }
          if (snapshot.hasError) {
            final error = snapshot.error;
            final deleting = error is ApiException &&
                error.statusCode == 423 &&
                error.message == 'ACCOUNT_DELETION_IN_PROGRESS';
            if (deleting || resumeAccountDeletion) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const JiYiStatusBanner(
                    kind: JiYiStatusKind.warning,
                    title: '账号注销正在进行',
                    message: '普通数据访问已锁定。请继续完成注销；你也可以退出后稍后重新登录恢复。',
                  ),
                  const SizedBox(height: JiYiSpacing.md),
                  AccountDeleteSection(
                    api: api,
                    onIntentConfirmed: onAccountDeleteIntentConfirmed,
                    onDeleted: onAccountDeleted,
                    resumeInProgress: true,
                  ),
                  const SizedBox(height: JiYiSpacing.md),
                  OutlinedButton.icon(
                    onPressed: onLogout,
                    icon: const Icon(Icons.logout),
                    label: const Text('退出登录'),
                  ),
                ],
              );
            }
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const JiYiStatusBanner(
                  kind: JiYiStatusKind.error,
                  title: '无法读取个人资料',
                  message: '请检查网络后重试；你也可以先安全退出当前账号。',
                ),
                const SizedBox(height: JiYiSpacing.md),
                OutlinedButton.icon(
                  onPressed: onLogout,
                  icon: const Icon(Icons.logout),
                  label: const Text('退出登录'),
                ),
              ],
            );
          }

          final profile = snapshot.data!;
          // 时区继续展示服务端保存的真实 IANA timezone；UI 不自行猜测或覆盖。
          final nickname = profile['nickname']?.toString() ?? '用户';
          final email = profile['email']?.toString() ?? '';
          final timezone = profile['timezone']?.toString() ?? '未知';
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              JiYiSectionCard(
                leading: CircleAvatar(
                  backgroundColor: theme.colorScheme.primaryContainer,
                  foregroundColor: theme.colorScheme.onPrimaryContainer,
                  child: const Icon(Icons.person_outline),
                ),
                title: nickname,
                subtitle: '当前登录账号',
                child: Column(
                  children: [
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.mail_outline),
                      title: const Text('邮箱'),
                      subtitle: Text(email.isEmpty ? '未提供' : email),
                    ),
                    const Divider(),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.schedule_outlined),
                      title: const Text('时区'),
                      subtitle: Text(timezone),
                    ),
                  ],
                ),
              ),
              if (offlineQueue != null) ...[
                const SizedBox(height: JiYiSpacing.md),
                RecordingHealthSection(
                  api: api,
                  store: offlineQueue!,
                  nativeLocationController: nativeLocationController,
                ),
              ],
              const SizedBox(height: JiYiSpacing.md),
              _PrivacyControls(
                api: api,
                nativeLocationController: nativeLocationController,
              ),
              if (amapPrivacyConsent != null) ...[
                const SizedBox(height: JiYiSpacing.md),
                _AmapPrivacyControls(authority: amapPrivacyConsent!),
              ],
              if (nativeLocationController != null) ...[
                const SizedBox(height: JiYiSpacing.md),
                NativeLocationSection(
                  controller: nativeLocationController!,
                  revalidateAuthority: onRevalidateLocationAuthority ??
                      () async => nativeLocationController!.privacyStatusUnknown(),
                ),
              ],
              const SizedBox(height: JiYiSpacing.md),
              _ElderModeControls(
                api: api,
                initialEnabled: profile['elder_mode_enabled'] == true,
                onChanged: onElderModeChanged ?? (_) {},
              ),
              const SizedBox(height: JiYiSpacing.md),
              _AppearanceControls(
                mode: themeMode,
                onChanged: onThemeModeChanged,
              ),
              if (onStartOnboarding != null) ...[
                const SizedBox(height: JiYiSpacing.md),
                JiYiSectionCard(
                  leading: Icon(
                    Icons.route_outlined,
                    color: theme.colorScheme.primary,
                  ),
                  title: '新手引导',
                  subtitle: '随时重新体验“记住、找回、查看依据”，不会创建演示数据。',
                  child: OutlinedButton.icon(
                    key: const ValueKey('profile-restart-onboarding'),
                    onPressed: onStartOnboarding,
                    icon: const Icon(Icons.replay_outlined),
                    label: const Text('重新查看新手引导'),
                  ),
                ),
              ],
              const SizedBox(height: JiYiSpacing.md),
              AccountDeleteSection(
                api: api,
                onIntentConfirmed: onAccountDeleteIntentConfirmed,
                onDeleted: onAccountDeleted,
                resumeInProgress: resumeAccountDeletion,
              ),
              const SizedBox(height: JiYiSpacing.md),
              OutlinedButton.icon(
                onPressed: onLogout,
                icon: const Icon(Icons.logout),
                label: const Text('退出登录'),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _AmapPrivacyControls extends StatefulWidget {
  const _AmapPrivacyControls({required this.authority});

  final AmapPrivacyConsentAuthority authority;

  @override
  State<_AmapPrivacyControls> createState() => _AmapPrivacyControlsState();
}

class _AmapPrivacyControlsState extends State<_AmapPrivacyControls> {
  bool accepted = false;
  bool loading = true;
  String? error;
  Listenable? _listenable;

  @override
  void initState() {
    super.initState();
    final authority = widget.authority;
    if (authority is Listenable) {
      final listenable = authority as Listenable;
      _listenable = listenable;
      listenable.addListener(_authorityChanged);
    }
    unawaited(_refresh());
  }

  @override
  void didUpdateWidget(covariant _AmapPrivacyControls oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.authority == widget.authority) return;
    _listenable?.removeListener(_authorityChanged);
    _listenable = widget.authority is Listenable
        ? widget.authority as Listenable
        : null;
    _listenable?.addListener(_authorityChanged);
    unawaited(_refresh());
  }

  void _authorityChanged() => unawaited(_refresh());

  Future<void> _refresh() async {
    try {
      final next = await widget.authority.readAccepted();
      if (mounted) {
        setState(() {
          accepted = next;
          loading = false;
          error = null;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          accepted = false;
          loading = false;
          error = '地图服务授权状态暂时无法读取。';
        });
      }
    }
  }

  Future<void> _enable() async {
    if (loading) return;
    final enabled = await requestAmapPrivacyConsent(context, widget.authority);
    if (mounted && enabled) {
      setState(() {
        accepted = true;
        error = null;
      });
    }
  }

  Future<void> _revoke() async {
    if (loading) return;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      await widget.authority.revoke();
      if (mounted) {
        setState(() {
          accepted = false;
          loading = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          loading = false;
          error = '暂时无法撤销地图服务授权。';
        });
      }
    }
  }

  @override
  void dispose() {
    _listenable?.removeListener(_authorityChanged);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return JiYiSectionCard(
      leading: const Icon(Icons.map_outlined),
      title: '高德地图服务',
      subtitle: accepted ? '已授权，可展示真实地点地图。' : '未授权，不会创建高德地图视图。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            amapPrivacyDisclosure,
            style: TextStyle(height: 1.5),
          ),
          const SizedBox(height: JiYiSpacing.sm),
          if (accepted)
            OutlinedButton.icon(
              key: const ValueKey('amap-privacy-revoke'),
              onPressed: loading ? null : _revoke,
              icon: const Icon(Icons.block_outlined),
              label: const Text('撤销地图授权'),
            )
          else
            FilledButton.tonalIcon(
              key: const ValueKey('amap-privacy-enable'),
              onPressed: loading ? null : _enable,
              icon: const Icon(Icons.map_outlined),
              label: const Text('查看说明并启用地图'),
            ),
          if (error != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            JiYiStatusBanner(
              kind: JiYiStatusKind.error,
              message: error!,
            ),
          ],
        ],
      ),
    );
  }
}

class _ElderModeControls extends StatefulWidget {
  const _ElderModeControls({
    required this.api,
    required this.initialEnabled,
    required this.onChanged,
  });

  final JiYiApiClient api;
  final bool initialEnabled;
  final ValueChanged<bool> onChanged;

  @override
  State<_ElderModeControls> createState() => _ElderModeControlsState();
}

class _AppearanceControls extends StatelessWidget {
  const _AppearanceControls({required this.mode, this.onChanged});

  final ThemeMode mode;
  final ValueChanged<ThemeMode>? onChanged;

  @override
  Widget build(BuildContext context) {
    final enabled = onChanged != null;
    return JiYiSectionCard(
      leading: Icon(
        Icons.palette_outlined,
        color: Theme.of(context).colorScheme.primary,
      ),
      title: '外观',
      subtitle: '选择让你舒服的阅读方式。',
      child: Column(
        children: [
          _ThemeModeOption(
            value: ThemeMode.system,
            groupValue: mode,
            title: '跟随系统',
            subtitle: '白天与夜晚自动切换',
            enabled: enabled,
            onChanged: onChanged,
          ),
          const Divider(),
          _ThemeModeOption(
            value: ThemeMode.light,
            groupValue: mode,
            title: '晨曦暖白',
            subtitle: '柔和浅色，适合日间阅读',
            enabled: enabled,
            onChanged: onChanged,
          ),
          const Divider(),
          _ThemeModeOption(
            value: ThemeMode.dark,
            groupValue: mode,
            title: '夜航深蓝',
            subtitle: '低亮深色，适合夜间阅读',
            enabled: enabled,
            onChanged: onChanged,
          ),
        ],
      ),
    );
  }
}

class _ThemeModeOption extends StatelessWidget {
  const _ThemeModeOption({
    required this.value,
    required this.groupValue,
    required this.title,
    required this.subtitle,
    required this.enabled,
    required this.onChanged,
  });

  final ThemeMode value;
  final ThemeMode groupValue;
  final String title;
  final String subtitle;
  final bool enabled;
  final ValueChanged<ThemeMode>? onChanged;

  @override
  Widget build(BuildContext context) {
    return RadioListTile<ThemeMode>(
      contentPadding: EdgeInsets.zero,
      value: value,
      // ignore: deprecated_member_use
      groupValue: groupValue,
      // ignore: deprecated_member_use
      onChanged: enabled
          ? (next) {
              if (next != null) onChanged?.call(next);
            }
          : null,
      title: Text(title),
      subtitle: Text(subtitle),
    );
  }
}

class _ElderModeControlsState extends State<_ElderModeControls> {
  late bool enabled = widget.initialEnabled;
  bool loading = false;
  String? error;

  Future<void> toggle(bool next) async {
    if (loading) return;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final profile = await widget.api.updateElderMode(next);
      if (!mounted) return;
      final canonical = profile['elder_mode_enabled'] == true;
      setState(() => enabled = canonical);
      widget.onChanged(canonical);
    } on ApiException catch (exc) {
      if (mounted) setState(() => error = exc.message);
    } catch (_) {
      if (mounted) setState(() => error = '长辈模式更新失败');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return JiYiSectionCard(
      leading: const Icon(Icons.accessibility_new_outlined),
      title: '长辈模式',
      subtitle: '只调整你自己的文字、按钮和页面层级，不改变家庭、位置、记忆或隐私权限。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Material(
            type: MaterialType.transparency,
            child: Semantics(
              label: '长辈模式',
              toggled: enabled,
              child: SwitchListTile(
                key: const ValueKey('elder-mode-toggle'),
                contentPadding: EdgeInsets.zero,
                title: Text(enabled ? '已开启' : '未开启'),
                value: enabled,
                onChanged: loading ? null : (value) => unawaited(toggle(value)),
              ),
            ),
          ),
          if (error != null)
            JiYiStatusBanner(
              kind: JiYiStatusKind.error,
              message: error!,
            ),
        ],
      ),
    );
  }
}

class _PrivacyControls extends StatefulWidget {
  const _PrivacyControls({
    required this.api,
    this.nativeLocationController,
  });

  final JiYiApiClient api;
  final NativeLocationController? nativeLocationController;

  @override
  State<_PrivacyControls> createState() => _PrivacyControlsState();
}

class _PrivacyControlsState extends State<_PrivacyControls> {
  Map<String, dynamic>? status;
  bool loading = true;
  String? message;
  // 提示类型只控制展示样式；pause/resume 的成功失败仍以服务端结果为准。
  bool messageIsError = false;
  // statusIsStale 表示当前只能展示上一次已知状态，不能把它当成实时隐私状态。
  bool statusIsStale = false;

  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<void> refresh() async {
    if (mounted && !loading) {
      setState(() => loading = true);
    }
    try {
      final next = await widget.api.getPrivacyStatus();
      if (mounted) {
        // 刷新成功后才恢复为实时可信状态；状态值仍完全来自服务端响应。
        setState(() {
          status = next;
          statusIsStale = false;
          message = null;
          messageIsError = false;
        });
        final location = widget.nativeLocationController;
        if (location != null) {
          if (next['recording_paused'] == true) {
            await location.pauseForPrivacy();
          } else {
            // A passive refresh never resumes native production.
            location.markPrivacyActive();
          }
        }
      }
    } on ApiException catch (exc) {
      if (mounted) {
        // 读取失败时绝不把未知状态推断为“未暂停”；已有状态只能作为上一次已知值展示。
        setState(() {
          statusIsStale = status != null;
          message = exc.message;
          messageIsError = true;
        });
        await widget.nativeLocationController?.privacyStatusUnknown();
      }
    } finally {
      if (mounted) {
        setState(() => loading = false);
      }
    }
  }

  Future<void> apply(
    Future<Map<String, dynamic>> Function() action,
    String success, {
    Future<void> Function()? afterSuccess,
  }) async {
    setState(() {
      // 新动作开始时只重置提示样式；暂停时长与业务状态仍由服务端决定。
      loading = true;
      message = null;
      messageIsError = false;
    });
    try {
      final next = await action();
      if (mounted) {
        setState(() {
          // success 文案仍由调用方对应真实成功动作传入；这里只设置成功视觉。
          status = next;
          statusIsStale = false;
          message = success;
          messageIsError = false;
        });
        await afterSuccess?.call();
      }
    } on ApiException catch (exc) {
      if (mounted) {
        // pause/resume 的服务端错误保持 fail-visible，只加强错误状态视觉。
        setState(() {
          statusIsStale = status != null;
          message = exc.message;
          messageIsError = true;
        });
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // 隐私状态只消费服务端返回值；status 为空时必须保持 unknown，不能折算成 false。
    final theme = Theme.of(context);
    final hasKnownStatus = status != null;
    final paused = hasKnownStatus && status!['recording_paused'] == true;
    final until = hasKnownStatus ? status!['paused_until']?.toString() : null;

    if (loading && status == null) {
      return const JiYiSectionCard(
        title: '隐私与记录控制',
        child: Padding(
          padding: EdgeInsets.symmetric(vertical: JiYiSpacing.sm),
          child: Row(
            children: [
              SizedBox.square(
                dimension: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
              SizedBox(width: JiYiSpacing.sm),
              Expanded(child: Text('正在读取当前隐私状态…')),
            ],
          ),
        ),
      );
    }

    return JiYiSectionCard(
      leading: Icon(
        !hasKnownStatus
            ? Icons.error_outline
            : (paused
                  ? Icons.pause_circle_outline
                  : Icons.privacy_tip_outlined),
        color: !hasKnownStatus
            ? theme.colorScheme.error
            : (statusIsStale || paused)
            ? context.jiyiSemanticColors.warning
            : theme.colorScheme.primary,
      ),
      title: '隐私与记录控制',
      subtitle: '暂停只影响自动采集；你主动使用“记一下”仍然可以继续保存内容。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!hasKnownStatus)
            JiYiStatusBanner(
              kind: JiYiStatusKind.error,
              title: '无法确认当前隐私状态',
              message: message ?? '当前状态未知，请稍后重试。',
            )
          else
            JiYiStatusBanner(
              kind: statusIsStale
                  ? JiYiStatusKind.warning
                  : (paused ? JiYiStatusKind.warning : JiYiStatusKind.success),
              title: statusIsStale
                  ? (paused ? '上一次已知状态：自动采集已暂停' : '上一次已知状态：没有暂停自动采集')
                  : (paused ? '自动采集已暂停' : '当前没有暂停自动采集'),
              message: statusIsStale
                  ? '当前状态刷新失败，以下为上一次已知状态，可能不是最新。'
                  : paused
                  ? (until == null ? '暂停状态已生效。' : '暂停状态已生效，直到 $until。')
                  : '如果暂时不希望自动采集，可以选择一个暂停时长。',
            ),
          if (message != null && hasKnownStatus) ...[
            const SizedBox(height: JiYiSpacing.sm),
            JiYiStatusBanner(
              kind: messageIsError
                  ? JiYiStatusKind.error
                  : JiYiStatusKind.success,
              message: message!,
            ),
          ],
          const SizedBox(height: JiYiSpacing.md),
          Text('暂停时长', style: theme.textTheme.titleSmall),
          const SizedBox(height: JiYiSpacing.xs),
          // 四个时长仍调用原 pause API；这里只统一按钮层级与 loading disable 状态。
          Wrap(
            spacing: JiYiSpacing.xs,
            runSpacing: JiYiSpacing.xs,
            children: [
              OutlinedButton(
                onPressed: loading
                    ? null
                    : () => apply(
                          () => widget.api.pauseMemory(30),
                          '已暂停 30 分钟',
                          afterSuccess:
                              widget.nativeLocationController?.pauseForPrivacy,
                        ),
                child: const Text('30 分钟'),
              ),
              OutlinedButton(
                onPressed: loading
                    ? null
                    : () => apply(
                          () => widget.api.pauseMemory(60),
                          '已暂停 1 小时',
                          afterSuccess:
                              widget.nativeLocationController?.pauseForPrivacy,
                        ),
                child: const Text('1 小时'),
              ),
              OutlinedButton(
                onPressed: loading
                    ? null
                    : () => apply(
                          () => widget.api.pauseMemory(180),
                          '已暂停 3 小时',
                          afterSuccess:
                              widget.nativeLocationController?.pauseForPrivacy,
                        ),
                child: const Text('3 小时'),
              ),
              OutlinedButton(
                onPressed: loading
                    ? null
                    : () => apply(
                          widget.api.pauseMemoryToday,
                          '今天剩余时间已暂停',
                          afterSuccess:
                              widget.nativeLocationController?.pauseForPrivacy,
                        ),
                child: const Text('今天'),
              ),
            ],
          ),
          const SizedBox(height: JiYiSpacing.md),
          // 恢复按钮仍只在服务端状态 paused=true 时可用；历史 pause interval 与禁止补传语义不变。
          FilledButton.icon(
            onPressed: loading || !paused
                ? null
                : () => apply(
                      widget.api.resumeMemory,
                      '已恢复自动记录',
                      afterSuccess:
                          widget.nativeLocationController?.resumeAfterPrivacy,
                    ),
            icon: loading
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.play_arrow_rounded),
            label: const Text('恢复记录'),
          ),
        ],
      ),
    );
  }
}
