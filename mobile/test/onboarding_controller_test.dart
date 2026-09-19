import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/onboarding_controller.dart';
import 'package:jiyidashi/onboarding_state.dart';

const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

// [人工注释][S1-026] Controller 单测锁定“中途退出可恢复”与异步销毁边界，
// 不依赖 Widget、网络或 SQLite，失败时可以直接定位状态机语义。
class _Store implements OnboardingStateStore {
  OnboardingStatus? status;
  Completer<OnboardingStatus?>? delayedRead;

  @override
  Future<OnboardingStatus?> read(String ownerUserId) {
    final delayed = delayedRead;
    return delayed == null ? Future.value(status) : delayed.future;
  }

  @override
  Future<void> markInProgress(String ownerUserId) async {
    status = OnboardingStatus.inProgress;
  }

  @override
  Future<void> markSkipped(String ownerUserId) async {
    status = OnboardingStatus.skipped;
  }

  @override
  Future<void> markCompleted(String ownerUserId) async {
    status = OnboardingStatus.completed;
  }

  @override
  Future<void> close() async {}
}

void main() {
  test('in-progress state resumes while skipped/completed stay out of the way', () async {
    for (final status in <OnboardingStatus>[
      OnboardingStatus.inProgress,
      OnboardingStatus.skipped,
      OnboardingStatus.completed,
    ]) {
      final store = _Store()..status = status;
      final controller = OnboardingController(
        store: store,
        ownerUserId: owner,
        autoStartForNewRegistration: false,
      );

      await controller.initialize();

      if (status == OnboardingStatus.inProgress) {
        expect(controller.step, OnboardingStep.intro);
      } else {
        expect(controller.step, isNull);
      }
      controller.dispose();
    }
  });

  test('new registration persists in-progress and opens intro', () async {
    final store = _Store();
    final controller = OnboardingController(
      store: store,
      ownerUserId: owner,
      autoStartForNewRegistration: true,
    );

    await controller.initialize();

    expect(store.status, OnboardingStatus.inProgress);
    expect(controller.step, OnboardingStep.intro);
    controller.dispose();
  });

  test('late persisted-state read is ignored after controller dispose', () async {
    final store = _Store()..delayedRead = Completer<OnboardingStatus?>();
    final controller = OnboardingController(
      store: store,
      ownerUserId: owner,
      autoStartForNewRegistration: false,
    );
    var notifications = 0;
    controller.addListener(() => notifications += 1);

    final initialize = controller.initialize();
    controller.dispose();
    store.delayedRead!.complete(OnboardingStatus.inProgress);
    await initialize;

    expect(notifications, 0);
  });
}
