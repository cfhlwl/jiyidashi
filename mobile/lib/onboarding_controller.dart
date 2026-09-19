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

  OnboardingStep? get step => _step;
  String? get querySeed => _querySeed;
  String? get targetMemoryId => _targetMemoryId;

  int? get navigationIndex => switch (_step) {
        OnboardingStep.intro => 0,
        OnboardingStep.capture => 2,
        OnboardingStep.retrieve || OnboardingStep.trust => 3,
        null => null,
      };

  bool allowsNavigation(int value) {
    return switch (_step) {
      OnboardingStep.capture => value == 2,
      OnboardingStep.retrieve || OnboardingStep.trust => value == 3,
      _ => true,
    };
  }

  Future<void> initialize() async {
    if (autoStartForNewRegistration) {
      try {
        await store.markInProgress(ownerUserId);
      } catch (_) {
        // Persistence is UX state only. A new user still gets the in-memory guide, and
        // skip/complete remain fail-open so a local database fault cannot trap the account.
      }
      _showIntro();
      return;
    }

    try {
      final status = await store.read(ownerUserId);
      if (status == OnboardingStatus.inProgress) {
        _showIntro();
      }
    } catch (_) {
      // Existing users with unreadable/missing local state enter the product normally.
    }
  }

  void startFlow() {
    _step = OnboardingStep.capture;
    notifyListeners();
  }

  void authoritativeTextMemorySaved(String memoryId, String querySeed) {
    if (_step != OnboardingStep.capture) return;
    final normalizedId = memoryId.trim();
    final normalizedQuery = querySeed.trim();
    if (normalizedId.isEmpty || normalizedQuery.isEmpty) return;
    _targetMemoryId = normalizedId;
    _querySeed = normalizedQuery;
    _step = OnboardingStep.retrieve;
    notifyListeners();
  }

  void trustedEvidenceShown() {
    if (_step != OnboardingStep.retrieve) return;
    _step = OnboardingStep.trust;
    notifyListeners();
  }

  Future<void> restart() async {
    try {
      await store.markInProgress(ownerUserId);
    } catch (_) {
      // Explicit re-entry must still work in this session if local UX-state persistence fails.
    }
    _querySeed = null;
    _targetMemoryId = null;
    _showIntro();
  }

  Future<void> skip() async {
    try {
      await store.markSkipped(ownerUserId);
    } catch (_) {
      // Skip is fail-open by design; onboarding may never become an access gate.
    }
    _step = null;
    _querySeed = null;
    _targetMemoryId = null;
    notifyListeners();
  }

  Future<void> complete() async {
    try {
      await store.markCompleted(ownerUserId);
    } catch (_) {
      // Completion is also fail-open to avoid a permanent onboarding loop.
    }
    _step = null;
    _querySeed = null;
    _targetMemoryId = null;
    notifyListeners();
  }

  void _showIntro() {
    _step = OnboardingStep.intro;
    _querySeed = null;
    _targetMemoryId = null;
    notifyListeners();
  }
}
