import 'package:flutter/foundation.dart';

import 'onboarding_state.dart';

// [人工注释][S1-026] 引导状态机只编排真实 Capture/Query/Evidence 事件；不创建演示 Memory，也不绕过服务端可信门禁。

// The controller owns onboarding lifecycle and persistence so AppShell only wires
// real product events (capture/query/navigation) into a small state machine.
class OnboardingController extends ChangeNotifier {
  OnboardingController({
    required this.store,
    required this.ownerUserId,
    required this.autoStartForNewRegistration,
  });

  final OnboardingStateStore store;
  final String ownerUserId;
  final bool autoStartForNewRegistration;

  OnboardingStep? _step;
  String? _querySeed;
  String? _targetMemoryId;
  bool _disposed = false;
  bool _accountDeletionQuiesced = false;
  final Set<Future<void>> _pendingPersistence = <Future<void>>{};

  OnboardingStep? get step => _step;
  String? get querySeed => _querySeed;
  String? get targetMemoryId => _targetMemoryId;

  int? get navigationIndex => switch (_step) {
        OnboardingStep.intro => 0,
        OnboardingStep.capture => 2,
        OnboardingStep.retrieve || OnboardingStep.trust => 3,
        null => null,
      };

  Future<void> _persist(Future<void> Function() action) {
    if (_disposed || _accountDeletionQuiesced) {
      return Future<void>.value();
    }
    late final Future<void> tracked;
    tracked = action().whenComplete(() {
      _pendingPersistence.remove(tracked);
    });
    _pendingPersistence.add(tracked);
    return tracked;
  }

  Future<void> quiesceForAccountDeletion() async {
    // [人工注释][S1-022-FIX-006] 注销本地 purge 前先禁止新 onboarding 写入，并等待
    // 已经开始的 mark/restart/complete 持久化结束；否则它们可能在 deleteOwnerState()
    // 之后把当前 owner 行重新插回本机 SQLite。
    _accountDeletionQuiesced = true;
    final pending = List<Future<void>>.of(_pendingPersistence);
    if (pending.isNotEmpty) {
      await Future.wait(
        pending.map(
          (future) => future.catchError((_) {
            // Onboarding persistence 本来就是 fail-open UX 状态；quiesce 只关心 I/O 已结束。
          }),
        ),
      );
    }
  }

  Future<void> initialize() async {
    if (autoStartForNewRegistration) {
      try {
        await _persist(() => store.markInProgress(ownerUserId));
      } catch (_) {
        // Persistence is UX state only. A new user still gets the in-memory guide, and
        // skip/complete remain fail-open so a local database fault cannot trap the account.
      }
      _showIntro();
      return;
    }

    try {
      final status = await store.read(ownerUserId);
      if (_disposed) return;
      if (status == OnboardingStatus.inProgress) {
        _showIntro();
      }
    } catch (_) {
      // Existing users with unreadable/missing local state enter the product normally.
    }
  }

  void startFlow() {
    if (_disposed) return;
    _step = OnboardingStep.capture;
    _emit();
  }

  void authoritativeTextMemorySaved(String memoryId, String querySeed) {
    if (_disposed || _step != OnboardingStep.capture) return;
    final normalizedId = memoryId.trim();
    final normalizedQuery = querySeed.trim();
    if (normalizedId.isEmpty || normalizedQuery.isEmpty) return;
    _targetMemoryId = normalizedId;
    _querySeed = normalizedQuery;
    _step = OnboardingStep.retrieve;
    _emit();
  }

  void trustedEvidenceShown() {
    if (_disposed || _step != OnboardingStep.retrieve) return;
    _step = OnboardingStep.trust;
    _emit();
  }

  Future<void> restart() async {
    try {
      await _persist(() => store.markInProgress(ownerUserId));
    } catch (_) {
      // Explicit re-entry must still work in this session if local UX-state persistence fails.
    }
    if (_disposed) return;
    _querySeed = null;
    _targetMemoryId = null;
    _showIntro();
  }

  Future<void> skip() async {
    try {
      await _persist(() => store.markSkipped(ownerUserId));
    } catch (_) {
      // Skip is fail-open by design; onboarding may never become an access gate.
    }
    if (_disposed) return;
    _step = null;
    _querySeed = null;
    _targetMemoryId = null;
    _emit();
  }

  Future<void> complete() async {
    try {
      await _persist(() => store.markCompleted(ownerUserId));
    } catch (_) {
      // Completion is also fail-open to avoid a permanent onboarding loop.
    }
    if (_disposed) return;
    _step = null;
    _querySeed = null;
    _targetMemoryId = null;
    _emit();
  }

  void _showIntro() {
    if (_disposed) return;
    _step = OnboardingStep.intro;
    _querySeed = null;
    _targetMemoryId = null;
    _emit();
  }

  void _emit() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    // [人工注释][S1-026] 本地状态 I/O 可能跨过 AppShell 销毁边界；
    // disposed 后所有异步续体都必须静默停止，不能再向已经移除的监听器发事件。
    _disposed = true;
    _accountDeletionQuiesced = true;
    super.dispose();
  }
}
