import 'dart:async';

import 'package:flutter/material.dart';

import 'account_delete_section.dart';
import 'api_client.dart';
import 'location_sampling_coordinator.dart';
import 'native_location_bridge.dart';
import 'native_location_controller.dart';
import 'native_location_section.dart';
import 'native_motion_sampling_bridge.dart';
import 'offline_queue.dart';
import 'offline_sync.dart';
import 'onboarding_controller.dart';
import 'onboarding_flow.dart';
import 'onboarding_state.dart';
import 'place_detail_page.dart';
import 'reminder_page.dart';
import 'today_footprint_page.dart';

// [人工注释][S1-026] AppShell 只接线 Onboarding；首次自动触发仅来自注册成功，老账号不会因缺少本地状态被误判为新用户。
import 'unified_capture_section.dart';
import 'ui/jiyi_theme.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';

class JiYiApp extends StatefulWidget {
  const JiYiApp({
    super.key,
    this.api,
    this.offlineQueue,
    this.onboardingStore,
    this.locationBridge,
    this.motionSamplingBridge,
  });

  final JiYiApiClient? api;
  final OfflineQueueStore? offlineQueue;
  final OnboardingStateStore? onboardingStore;
  final NativeLocationBridge? locationBridge;
  final NativeMotionSamplingBridge? motionSamplingBridge;

  @override
  State<JiYiApp> createState() => _JiYiAppState();
}

class _JiYiAppState extends State<JiYiApp> {
  late final JiYiApiClient api = widget.api ?? JiYiApiClient();
  // [人工注释][S1-015] App 级共享一个 SQLite queue store；测试可注入独立数据库，生产默认使用系统数据库目录。
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
  bool authenticated = false;
  bool startOnboardingAfterAuth = false;
  bool resumeAccountDeletionAfterAuth = false;
  bool elderModeEnabled = false;

  @override
  void dispose() {
    // [人工注释][S1-015] 只关闭本组件自己创建的数据库句柄；外部注入 Store 的生命周期由调用方负责。
    if (widget.offlineQueue == null) {
      unawaited(offlineQueue.close());
    }
    if (widget.onboardingStore == null) {
      unawaited(onboardingStore.close());
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '迹忆',
      debugShowCheckedModeBanner: false,
      // 生产 Theme 改为单一事实源；G1 参数与原 Theme 完全一致，预期不产生视觉漂移。
      theme: JiYiTheme.light(elderMode: elderModeEnabled),
      home: authenticated
          ? AppShell(
              api: api,
              offlineQueue: offlineQueue,
              onboardingStore: onboardingStore,
              startOnboarding: startOnboardingAfterAuth,
              resumeAccountDeletion: resumeAccountDeletionAfterAuth,
              locationBridge: locationBridge,
              motionSamplingBridge: widget.motionSamplingBridge,
              sync: sync,
              onElderModeChanged: (enabled) {
                if (mounted) setState(() => elderModeEnabled = enabled);
              },
              onLogout: () {
                api.logout();
                setState(() {
                  authenticated = false;
                  startOnboardingAfterAuth = false;
                  resumeAccountDeletionAfterAuth = false;
                  elderModeEnabled = false;
                });
              },
            )
          : AuthPage(
              api: api,
              onRegistrationCompleted: () {
                startOnboardingAfterAuth = true;
                resumeAccountDeletionAfterAuth = false;
              },
              onAccountDeletionRecovery: () {
                // [人工注释][S1-022-FIX-001] 恢复登录只进入注销收尾，不启动普通数据空间/离线同步。
                resumeAccountDeletionAfterAuth = true;
                startOnboardingAfterAuth = false;
              },
              onAuthenticated: () => setState(() => authenticated = true),
            ),
    );
  }
}

class AuthPage extends StatefulWidget {
  const AuthPage({
    super.key,
    required this.api,
    required this.onAuthenticated,
    this.onRegistrationCompleted,
    this.onAccountDeletionRecovery,
  });

  final JiYiApiClient api;
  final VoidCallback onAuthenticated;
  final VoidCallback? onRegistrationCompleted;
  final VoidCallback? onAccountDeletionRecovery;

  @override
  State<AuthPage> createState() => _AuthPageState();
}

class _AuthPageState extends State<AuthPage> {
  final emailController = TextEditingController();
  final passwordController = TextEditingController();
  final nicknameController = TextEditingController();
  bool registerMode = false;
  bool loading = false;
  String? error;

  @override
  void dispose() {
    emailController.dispose();
    passwordController.dispose();
    nicknameController.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    if (emailController.text.trim().isEmpty ||
        passwordController.text.isEmpty) {
      setState(() => error = '请输入邮箱和密码');
      return;
    }
    if (registerMode && nicknameController.text.trim().isEmpty) {
      setState(() => error = '请输入昵称');
      return;
    }
    setState(() {
      loading = true;
      error = null;
    });
    try {
      // [人工注释][S1-001] 登录/注册成功后才进入个人记忆空间，匿名用户不能调用个人数据 API。
      if (registerMode) {
        await widget.api.register(
          email: emailController.text,
          password: passwordController.text,
          nickname: nicknameController.text,
        );
        // Only a confirmed new registration auto-starts onboarding. Existing users
        // logging into an upgraded app are never inferred to be "new" from missing local state.
        widget.onRegistrationCompleted?.call();
      } else {
        final login = await widget.api.login(
          email: emailController.text,
          password: passwordController.text,
        );
        if (login['account_deletion_in_progress'] == true) {
          widget.onAccountDeletionRecovery?.call();
        }
      }
      widget.onAuthenticated();
    } on ApiException catch (exc) {
      setState(() => error = exc.message);
    } catch (_) {
      setState(() => error = '暂时无法连接服务器');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
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
                    // 登录页品牌区只增强视觉识别，不增加未实现能力或营销承诺。
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
                      title: registerMode ? '创建你的记忆空间' : '欢迎回来',
                      subtitle: registerMode
                          ? '注册后，你的记录、找回和隐私设置都归属于自己的账号。'
                          : '登录后继续查看和管理属于你的可信记忆。',
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
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
                          TextField(
                            controller: passwordController,
                            obscureText: true,
                            textInputAction: registerMode
                                ? TextInputAction.next
                                : TextInputAction.done,
                            onSubmitted: loading || registerMode
                                ? null
                                : (_) => submit(),
                            decoration: const InputDecoration(
                              labelText: '密码',
                              prefixIcon: Icon(Icons.lock_outline),
                            ),
                          ),
                          if (registerMode) ...[
                            const SizedBox(height: JiYiSpacing.sm),
                            TextField(
                              controller: nicknameController,
                              textInputAction: TextInputAction.done,
                              onSubmitted: loading ? null : (_) => submit(),
                              decoration: const InputDecoration(
                                labelText: '昵称',
                                prefixIcon: Icon(Icons.person_outline),
                              ),
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
                          FilledButton.icon(
                            onPressed: loading ? null : submit,
                            icon: loading
                                ? const SizedBox.square(
                                    dimension: 18,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : Icon(
                                    registerMode
                                        ? Icons.person_add_alt_1_outlined
                                        : Icons.login,
                                  ),
                            label: Text(
                              loading ? '请稍候…' : (registerMode ? '创建账号' : '登录'),
                            ),
                          ),
                          const SizedBox(height: JiYiSpacing.xs),
                          TextButton(
                            onPressed: loading
                                ? null
                                : () => setState(() {
                                    registerMode = !registerMode;
                                    error = null;
                                  }),
                            child: Text(
                              registerMode ? '已有账号？返回登录' : '第一次使用？创建账号',
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (widget.api.showDevelopmentEndpoint) ...[
                      // [人工注释][S1-FIX-007] 生产构建不渲染开发 API 信息，endpoint 只能由 build-time 配置注入。
                      const SizedBox(height: JiYiSpacing.md),
                      Text(
                        '当前开发环境 API：${widget.api.baseUrl}',
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
    this.sync,
    required this.onElderModeChanged,
    required this.onLogout,
  });

  final JiYiApiClient api;
  final OfflineQueueStore offlineQueue;
  final OnboardingStateStore? onboardingStore;
  final bool startOnboarding;
  final bool resumeAccountDeletion;
  final NativeLocationBridge? locationBridge;
  final NativeMotionSamplingBridge? motionSamplingBridge;
  final OfflineSyncCoordinator? sync;
  final ValueChanged<bool> onElderModeChanged;
  final VoidCallback onLogout;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> with WidgetsBindingObserver {
  late final OfflineSyncCoordinator _sync =
      widget.sync ?? OfflineSyncCoordinator(api: widget.api, store: widget.offlineQueue);
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
    _accountDeletionIntentActive = widget.resumeAccountDeletion;
    if (_accountDeletionIntentActive) {
      index = 4;
    }
    final store = widget.onboardingStore;
    final owner = widget.api.authenticatedUserId?.trim();
    if (owner != null && owner.isNotEmpty) {
      final location = NativeLocationController(
        bridge: widget.locationBridge ?? MethodChannelNativeLocationBridge(),
        ownerUserId: owner,
      );
      _nativeLocation = location;
      _locationSampling = LocationSamplingCoordinator(
        api: widget.api,
        store: widget.offlineQueue,
        locationController: location,
        nativeBridge:
            widget.motionSamplingBridge ?? MethodChannelNativeMotionSamplingBridge(),
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

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
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
      widget.onElderModeChanged(enabled);
    } catch (_) {
      if (!mounted ||
          widget.api.sessionVersion != sessionVersion ||
          widget.api.authenticatedUserId != owner) {
        return;
      }
      setState(() => _elderModeEnabled = false);
      widget.onElderModeChanged(false);
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
        index = 4;
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
    final pages = <Widget>[
      TodayPage(api: widget.api),
      TimelinePage(api: widget.api),
      CapturePage(
        api: widget.api,
        offlineQueue: widget.offlineQueue,
        sync: _sync,
        syncGeneration: syncGeneration,
        onQueueChanged: _queueChanged,
        onAuthoritativeTextMemorySaved:
            onboardingStep == OnboardingStep.capture
                ? onboarding?.authoritativeTextMemorySaved
                : null,
      ),
      MemoryQueryPage(
        api: widget.api,
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
      ),
      ProfilePage(
        api: widget.api,
        elderModeEnabled: _elderModeEnabled,
        onElderModeChanged: (enabled) {
          setState(() => _elderModeEnabled = enabled);
          widget.onElderModeChanged(enabled);
        },
        onLogout: () => unawaited(_stopLocationAndLogout()),
        onAccountDeleteIntentConfirmed: _prepareLocalAccountDeletion,
        onAccountDeleted: () async => _stopLocationAndLogout(),
        resumeAccountDeletion: _accountDeletionIntentActive,
        nativeLocationController: _nativeLocation,
        onStartOnboarding: onboarding == null
            ? null
            : () => unawaited(onboarding.restart()),
      ),
    ];
    return Scaffold(
      body: SafeArea(
        child: OnboardingExperience(
          step: _accountDeletionIntentActive ? null : onboardingStep,
          onStart: onboarding?.startFlow ?? () {},
          onSkip: () {
            if (onboarding != null) unawaited(onboarding.skip());
          },
          onComplete: () {
            if (onboarding != null) unawaited(onboarding.complete());
          },
          child: pages[index],
        ),
      ),
      // [人工注释][S1-026] 引导进行时由 GuideBar 提供唯一退出入口；隐藏而不是保留“看得见但点不动”的底部导航。
      bottomNavigationBar: onboardingStep != null || _accountDeletionIntentActive
          ? null
          : NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (value) => setState(() => index = value),
        // destination 数量/顺序/索引语义不变，只补充清晰的选中态图标。
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.today_outlined),
            selectedIcon: const Icon(Icons.today),
            label: _elderModeEnabled ? '今天去了哪里' : '今天',
          ),
          NavigationDestination(
            icon: const Icon(Icons.timeline_outlined),
            selectedIcon: const Icon(Icons.timeline),
            label: '时间轴',
          ),
          NavigationDestination(
            icon: const Icon(Icons.add_circle_outline),
            selectedIcon: const Icon(Icons.add_circle),
            label: '记一下',
          ),
          NavigationDestination(
            icon: const Icon(Icons.psychology_alt_outlined),
            selectedIcon: const Icon(Icons.psychology_alt),
            label: _elderModeEnabled ? '找东西' : '问记忆',
          ),
          NavigationDestination(
            icon: const Icon(Icons.person_outline),
            selectedIcon: const Icon(Icons.person),
            label: '我的',
          ),
        ],
      ),
    );
  }
}

class TimelinePage extends StatefulWidget {
  const TimelinePage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<TimelinePage> createState() => _TimelinePageState();
}

class _TimelinePageState extends State<TimelinePage> {
  late Future<List<Map<String, dynamic>>> _places = widget.api.listPlaces();

  void _retryPlaces() {
    setState(() => _places = widget.api.listPlaces());
  }

  @override
  Widget build(BuildContext context) {
    return JiYiPageFrame(
      title: '时间轴',
      subtitle: '按时间回看已经形成的可信记忆。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const JiYiSectionCard(
            child: JiYiEmptyState(
              icon: Icons.route_outlined,
              title: '自动足迹尚未开放',
              message: '今日足迹仍由后续 S2-012 实现；这里不提前推断今天去了哪里。',
            ),
          ),
          const SizedBox(height: JiYiSpacing.md),
          JiYiSectionCard(
            title: '地点',
            subtitle: '查看已经形成的地点和 retained Visit 详情。',
            child: FutureBuilder<List<Map<String, dynamic>>>(
              future: _places,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Center(
                    child: Padding(
                      padding: EdgeInsets.all(JiYiSpacing.md),
                      child: CircularProgressIndicator(),
                    ),
                  );
                }
                if (snapshot.hasError) {
                  final error = snapshot.error;
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      JiYiStatusBanner(
                        kind: JiYiStatusKind.error,
                        title: '地点列表读取失败',
                        message: error is ApiException
                            ? error.message
                            : '暂时无法读取地点',
                      ),
                      const SizedBox(height: JiYiSpacing.sm),
                      OutlinedButton(
                        onPressed: _retryPlaces,
                        child: const Text('重试'),
                      ),
                    ],
                  );
                }
                final places = snapshot.data ?? const <Map<String, dynamic>>[];
                if (places.isEmpty) {
                  return const JiYiEmptyState(
                    icon: Icons.place_outlined,
                    title: '还没有地点',
                    message: '形成 retained Visit 后，这里才会出现可查看的地点。',
                  );
                }
                return Column(
                  children: [
                    for (var i = 0; i < places.length; i++) ...[
                      // [人工注释][S2-013] JiYiSectionCard 使用 DecoratedBox；
                      // ListTile 需要自己的透明 Material 承载 ink，不能让点击反馈被卡片背景遮住。
                      Material(
                        type: MaterialType.transparency,
                        child: ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: const Icon(Icons.place_outlined),
                          title: Text(
                            places[i]['name']?.toString() ?? '未命名地点',
                          ),
                          subtitle: Text(
                            places[i]['address']?.toString() ?? '暂无地址信息',
                          ),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () {
                            final placeId = places[i]['id']?.toString() ?? '';
                            if (placeId.isEmpty) return;
                            Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) => PlaceDetailPage(
                                  api: widget.api,
                                  placeId: placeId,
                                ),
                              ),
                            );
                          },
                        ),
                      ),
                      if (i != places.length - 1)
                        const Divider(height: JiYiSpacing.sm),
                    ],
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class CapturePage extends StatefulWidget {
  const CapturePage({
    super.key,
    required this.api,
    required this.offlineQueue,
    this.sync,
    this.syncGeneration = 0,
    this.onQueueChanged,
    this.onAuthoritativeTextMemorySaved,
  });

  final JiYiApiClient api;
  final OfflineQueueStore offlineQueue;
  final OfflineSyncCoordinator? sync;
  final int syncGeneration;
  final VoidCallback? onQueueChanged;
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

  late final OfflineSyncCoordinator _sync =
      widget.sync ?? OfflineSyncCoordinator(api: widget.api, store: widget.offlineQueue);

  @override
  void initState() {
    super.initState();
    unawaited(_refreshOfflinePendingCount());
  }

  @override
  void didUpdateWidget(covariant CapturePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.syncGeneration != widget.syncGeneration) {
      unawaited(_refreshOfflinePendingCount());
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
        setState(() => result = '✓ 已记住 · ${current.serverResourceId}');
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
        setState(() => result = '✓ 已记录当前位置 · ${current.serverResourceId}');
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
      title: '记一下',
      subtitle: '把重要的内容或物品位置清楚地记下来。',
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
          JiYiSectionCard(
            leading: Icon(
              Icons.edit_note_outlined,
              color: theme.colorScheme.primary,
            ),
            title: '写一句',
            subtitle: '适合记录临时安排、承诺、重要提醒或一段想留下的话。',
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
          // 图片与语音继续复用既有 verified media / ASR Evidence 协议；
          // 文字与物品位置仍由上方 outbox-first 路径负责，避免媒体大文件进入 SQLite。
          UnifiedMediaCaptureSection(api: widget.api),
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
              '编辑会保留原始 Evidence；正文修改会记录为新的用户修正来源。',
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

class MemoryQueryPage extends StatefulWidget {
  const MemoryQueryPage({
    super.key,
    required this.api,
    this.initialQuestion,
    this.requiredEvidenceMemoryId,
    this.onTrustedEvidenceShown,
  });

  final JiYiApiClient api;
  final String? initialQuestion;
  final String? requiredEvidenceMemoryId;
  final VoidCallback? onTrustedEvidenceShown;

  @override
  State<MemoryQueryPage> createState() => _MemoryQueryPageState();
}

class _MemoryQueryPageState extends State<MemoryQueryPage> {
  final controller = TextEditingController();
  Map<String, dynamic>? result;
  String? error;
  String? actionMessage;
  bool loading = false;

  @override
  void initState() {
    super.initState();
    final initial = widget.initialQuestion?.trim();
    if (initial != null && initial.isNotEmpty) {
      controller.text = initial;
    }
  }

  @override
  void didUpdateWidget(covariant MemoryQueryPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    final next = widget.initialQuestion?.trim();
    if (oldWidget.initialQuestion != widget.initialQuestion &&
        controller.text.trim().isEmpty &&
        next != null &&
        next.isNotEmpty) {
      controller.text = next;
    }
  }

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  Future<void> query() async {
    if (controller.text.trim().isEmpty) {
      return;
    }
    setState(() {
      loading = true;
      error = null;
      actionMessage = null;
    });
    try {
      final response = await widget.api.queryMemory(controller.text);
      if (!mounted) return;
      setState(() => result = response);
      final evidence = response['evidence'];
      final memoryIds = response['memory_ids'];
      final requiredMemoryId = widget.requiredEvidenceMemoryId?.trim();
      final containsRequiredMemory = requiredMemoryId == null ||
          requiredMemoryId.isEmpty ||
          (memoryIds is List<dynamic> &&
              memoryIds.any((value) => value.toString() == requiredMemoryId));
      if (response['can_answer'] == true &&
          evidence is List<dynamic> &&
          evidence.isNotEmpty &&
          containsRequiredMemory) {
        // Onboarding advances only when the real query points back to the Memory that
        // this flow just saved. Evidence for an unrelated older Memory is not the Aha.
        widget.onTrustedEvidenceShown?.call();
      }
    } on ApiException catch (exc) {
      setState(() => error = exc.message);
    } catch (_) {
      setState(() => error = '暂时无法连接服务器');
    } finally {
      if (mounted) {
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
      setState(() => error = '服务端返回的记忆版本不正确，请重新查询后再试');
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
        actionMessage = '✓ 记忆已更新；原始 Evidence 与编辑记录均已保留';
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

    setState(() => loading = true);
    try {
      // [人工注释][S1-019] 只有服务端 DELETE 成功后才清空当前答案，
      // 这样“删除”才是真正影响后续检索的业务操作。
      await widget.api.deleteMemory(ids.first.toString());
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

  @override
  Widget build(BuildContext context) {
    // G4 仅重排 Query/Evidence/删除入口的展示层；答案、Evidence、memory_ids 都继续直接使用服务端真实返回。
    final theme = Theme.of(context);
    final evidence = (result?['evidence'] as List<dynamic>? ?? const []);
    final memoryIds = (result?['memory_ids'] as List<dynamic>? ?? const []);
    final canAnswer = result?['can_answer'] == true;
    final answer = result?['answer']?.toString() ?? '';
    final certainty = result?['certainty']?.toString() ?? '未知';
    final intent = result?['intent']?.toString() ?? '未知';
    // FIND_OBJECT 的 backing Memory 受结构化 ObjectLocation 状态约束，
    // 通用编辑会被后端拒绝，因此 UI 直接隐藏编辑入口而不是让用户走到 409。
    final canEditFirstMemory = memoryIds.isNotEmpty && intent != 'FIND_OBJECT';

    return JiYiPageFrame(
      title: '问记忆',
      subtitle: '从你自己的记录里查找；答案会把依据一起展示出来。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          JiYiSectionCard(
            leading: Icon(
              Icons.psychology_alt_outlined,
              color: theme.colorScheme.primary,
            ),
            title: '问一个问题',
            subtitle: '找不到可靠依据时，迹忆会明确告诉你，而不是猜一个答案。',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  key: const ValueKey('memory-query-input'),
                  controller: controller,
                  textInputAction: TextInputAction.search,
                  onSubmitted: loading ? null : (_) => query(),
                  decoration: const InputDecoration(
                    labelText: '你想回忆什么？',
                    hintText: '例如：我的护照在哪里？',
                    prefixIcon: Icon(Icons.search),
                  ),
                ),
                const SizedBox(height: JiYiSpacing.md),
                FilledButton.icon(
                  key: const ValueKey('memory-query-submit'),
                  onPressed: loading ? null : query,
                  icon: loading
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.manage_search_outlined),
                  label: Text(loading ? '查找中…' : '从我的记忆里查找'),
                ),
              ],
            ),
          ),
          if (error != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            JiYiStatusBanner(
              kind: JiYiStatusKind.error,
              title: '暂时无法查找',
              message: error!,
            ),
          ],
          if (actionMessage != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            JiYiStatusBanner(
              kind: JiYiStatusKind.success,
              message: actionMessage!,
            ),
          ],
          if (result != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            JiYiSectionCard(
              leading: Icon(
                canAnswer ? Icons.lightbulb_outline : Icons.search_off_outlined,
                color: canAnswer
                    ? theme.colorScheme.primary
                    : theme.colorScheme.onSurfaceVariant,
              ),
              title: canAnswer ? '找到相关记忆' : '没有足够依据',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    canAnswer && answer.isNotEmpty
                        ? answer
                        : '我没有找到能够支持答案的相关记录。',
                    style: theme.textTheme.titleMedium,
                  ),
                  const SizedBox(height: JiYiSpacing.sm),
                  // certainty / intent 不被 UI 重新推断；这里只把服务端原值放入有标签的 Chip，避免弱化可信状态。
                  Wrap(
                    spacing: JiYiSpacing.xs,
                    runSpacing: JiYiSpacing.xs,
                    children: [
                      Chip(
                        avatar: const Icon(Icons.verified_outlined, size: 18),
                        label: Text('可信状态：$certainty'),
                      ),
                      Chip(
                        avatar: const Icon(Icons.category_outlined, size: 18),
                        label: Text('识别意图：$intent'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            if (evidence.isNotEmpty) ...[
              const SizedBox(height: JiYiSpacing.lg),
              Text('为什么这么回答', style: theme.textTheme.titleMedium),
              const SizedBox(height: JiYiSpacing.xs),
              Text(
                '下面是这次回答实际使用的证据。',
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: JiYiSpacing.sm),
              ...evidence.map((item) {
                final e = item as Map<String, dynamic>;
                final sourceLabel =
                    _evidenceSourceLabel(e['source_type']?.toString());
                final provenance = e['provenance']?.toString();
                // USER_EDIT 明确告诉用户当前文字来自后续手工修正，不能继续伪装成原始媒体证明。
                final displayedSource = provenance == 'USER_EDIT'
                    ? '$sourceLabel · 用户编辑'
                    : sourceLabel;
                return Padding(
                  padding: const EdgeInsets.only(bottom: JiYiSpacing.sm),
                  child: JiYiEvidenceCard(
                    excerpt: e['excerpt']?.toString() ?? '',
                    source: displayedSource,
                    evidenceType: e['kind']?.toString() ?? '未知',
                    occurredAt: e['occurred_at']?.toString() ?? '未知',
                    confidence: e['confidence']?.toString() ?? '未知',
                  ),
                );
              }),
            ] else if (canAnswer) ...[
              const SizedBox(height: JiYiSpacing.md),
              // 若服务端声称可回答却没有可展示 Evidence，UI 明确暴露该异常事实，不用美化层隐藏。
              const JiYiStatusBanner(
                kind: JiYiStatusKind.warning,
                title: '没有可展示的证据',
                message: '这次响应没有返回 Evidence，请谨慎使用这个答案。',
              ),
            ],
            if (memoryIds.isNotEmpty) ...[
              const SizedBox(height: JiYiSpacing.md),
              JiYiSectionCard(
                leading: Icon(
                  Icons.delete_outline,
                  color: theme.colorScheme.error,
                ),
                title: '管理这条记忆',
                subtitle: '可设置一次性提醒；编辑保留原始 Evidence，删除会影响后续检索。',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    FilledButton.tonalIcon(
                      key: const ValueKey('memory-reminder-open'),
                      onPressed: loading ? null : createReminderForFirstMemory,
                      icon: const Icon(Icons.alarm_add_outlined),
                      label: const Text('为这条记忆设置提醒'),
                    ),
                    const SizedBox(height: JiYiSpacing.sm),
                    OutlinedButton.icon(
                      key: const ValueKey('open-reminder-management'),
                      onPressed: loading
                          ? null
                          : () {
                              Navigator.of(context).push(
                                MaterialPageRoute(
                                  builder: (_) => ReminderPage(api: widget.api),
                                ),
                              );
                            },
                      icon: const Icon(Icons.alarm_outlined),
                      label: const Text('查看提醒管理'),
                    ),
                    const SizedBox(height: JiYiSpacing.sm),
                    if (canEditFirstMemory) ...[
                      FilledButton.tonalIcon(
                        key: const ValueKey('memory-edit-open'),
                        onPressed: loading ? null : editFirstMemory,
                        icon: const Icon(Icons.edit_outlined),
                        label: const Text('编辑最相关记忆'),
                      ),
                      const SizedBox(height: JiYiSpacing.sm),
                    ],
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
        ],
      ),
    );
  }
}

class ProfilePage extends StatelessWidget {
  const ProfilePage({
    super.key,
    required this.api,
    required this.elderModeEnabled,
    required this.onElderModeChanged,
    required this.onLogout,
    required this.onAccountDeleteIntentConfirmed,
    required this.onAccountDeleted,
    this.resumeAccountDeletion = false,
    this.nativeLocationController,
    this.onStartOnboarding,
  });

  final JiYiApiClient api;
  final bool elderModeEnabled;
  final ValueChanged<bool> onElderModeChanged;
  final VoidCallback onLogout;
  final Future<void> Function() onAccountDeleteIntentConfirmed;
  final Future<void> Function() onAccountDeleted;
  final bool resumeAccountDeletion;
  final NativeLocationController? nativeLocationController;
  final VoidCallback? onStartOnboarding;

  @override
  Widget build(BuildContext context) {
    // G5 只统一 Profile 的 loading/error/account 信息层级；资料仍完全来自 getProfile() 的真实响应。
    final theme = Theme.of(context);
    return JiYiPageFrame(
      title: '我的',
      subtitle: '管理账号信息、时区和隐私控制。',
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
              const SizedBox(height: JiYiSpacing.md),
              _ElderModeControls(
                api: api,
                initialEnabled: profile['elder_mode_enabled'] == true,
                onChanged: onElderModeChanged,
              ),
              const SizedBox(height: JiYiSpacing.md),
              _PrivacyControls(
                api: api,
                nativeLocationController: nativeLocationController,
              ),
              if (nativeLocationController != null) ...[
                const SizedBox(height: JiYiSpacing.md),
                NativeLocationSection(controller: nativeLocationController!),
              ],
              if (onStartOnboarding != null) ...[
                const SizedBox(height: JiYiSpacing.md),
                JiYiSectionCard(
                  leading: Icon(
                    Icons.route_outlined,
                    color: theme.colorScheme.primary,
                  ),
                  title: '新手引导',
                  subtitle: '随时重新体验“记住、找回、查看 Evidence”，不会创建演示数据。',
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
          Semantics(
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
