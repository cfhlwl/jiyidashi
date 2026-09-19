import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/onboarding_state.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// [人工注释][S1-026] 验证引导状态持久化、重启恢复和多账号隔离。

const userA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const userB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

void main() {
  sqfliteFfiInit();
  final testDatabaseFactory = databaseFactoryFfiNoIsolate;

  late Directory tempDirectory;
  late String databasePath;

  setUp(() async {
    tempDirectory = await Directory.systemTemp.createTemp('jiyidashi-onboarding-');
    databasePath = '${tempDirectory.path}${Platform.pathSeparator}onboarding.sqlite3';
  });

  tearDown(() async {
    await testDatabaseFactory.deleteDatabase(databasePath);
    if (await tempDirectory.exists()) {
      await tempDirectory.delete(recursive: true);
    }
  });

  OnboardingStore createStore() {
    return OnboardingStore(
      factory: testDatabaseFactory,
      databasePathProvider: () async => databasePath,
      now: () => DateTime.utc(2026, 9, 19, 3),
    );
  }

  test('status survives reopen and stays isolated by authenticated user id', () async {
    final first = createStore();
    expect(await first.read(userA), isNull);
    expect(await first.read(userB), isNull);

    await first.markInProgress(userA);
    expect(await first.read(userA), OnboardingStatus.inProgress);
    expect(await first.read(userB), isNull);
    await first.close();

    final reopened = createStore();
    expect(await reopened.read(userA), OnboardingStatus.inProgress);
    await reopened.markSkipped(userA);
    await reopened.markCompleted(userB);

    expect(await reopened.read(userA), OnboardingStatus.skipped);
    expect(await reopened.read(userB), OnboardingStatus.completed);
    await reopened.close();
  });

  test('empty owner is rejected instead of creating unscoped device state', () async {
    final store = createStore();
    await expectLater(store.markCompleted('  '), throwsArgumentError);
    await store.close();
  });
}
