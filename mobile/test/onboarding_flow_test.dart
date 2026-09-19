import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/onboarding_flow.dart';
import 'package:jiyidashi/onboarding_state.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const memoryId = '11111111-1111-4111-8111-111111111111';

class _MemoryOnboardingStore implements OnboardingStateStore {
  final Map<String, OnboardingStatus> values = <String, OnboardingStatus>{};

  @override
  Future<OnboardingStatus?> read(String ownerUserId) async => values[ownerUserId];

  @override
  Future<void> markInProgress(String ownerUserId) async {
    values[ownerUserId] = OnboardingStatus.inProgress;
  }

  @override
  Future<void> markSkipped(String ownerUserId) async {
    values[ownerUserId] = OnboardingStatus.skipped;
  }

  @override
  Future<void> markCompleted(String ownerUserId) async {
    values[ownerUserId] = OnboardingStatus.completed;
  }

  @override
  Future<void> close() async {}
}


class _ZeroQueue extends OfflineQueueStore {
  @override
  Future<int> countAwaitingDelivery(String ownerUserId) async => 0;

  @override
  Future<void> close() async {}
}

class _AuthenticationApi extends JiYiApiClient {
  _AuthenticationApi() : super(baseUrl: 'https://auth-onboarding.invalid/v1');

  void _authenticate() {
    accessToken = 'auth-onboarding-token';
    authenticatedUserId = owner;
  }

  @override
  Future<Map<String, dynamic>> register({
    required String email,
    required String password,
    required String nickname,
    String timezone = 'Asia/Shanghai',
    String locale = 'zh-CN',
  }) async {
    _authenticate();
    return <String, dynamic>{
      'access_token': accessToken,
      'token_type': 'bearer',
      'user_id': owner,
    };
  }

  @override
  Future<Map<String, dynamic>> login({
    required String email,
    required String password,
  }) async {
    _authenticate();
    return <String, dynamic>{
      'access_token': accessToken,
      'token_type': 'bearer',
      'user_id': owner,
    };
  }
}

class _OnboardingApi extends JiYiApiClient {
  _OnboardingApi() : super(baseUrl: 'https://onboarding.invalid/v1') {
    accessToken = 'onboarding-token';
    authenticatedUserId = owner;
  }

  String? savedContent;
  String? queriedQuestion;
  String queryMemoryId = memoryId;

  @override
  Future<Map<String, dynamic>> createTextMemory({
    String? title,
    required String content,
    DateTime? occurredAt,
    String? clientUuid,
  }) async {
    savedContent = content;
    return <String, dynamic>{
      'id': memoryId,
      'content': content,
      'title': title,
    };
  }

  @override
  Future<Map<String, dynamic>> queryMemory(String question) async {
    queriedQuestion = question;
    final content = savedContent;
    final found = content != null && question.trim() == content;
    return <String, dynamic>{
      'answer': found ? content : '',
      'can_answer': found,
      'certainty': found ? 'confirmed' : 'unknown',
      'reason': found ? null : 'NO_EVIDENCE',
      'intent': 'GENERAL',
      'memory_ids': found ? <String>[queryMemoryId] : <String>[],
      'evidence': found
          ? <Map<String, dynamic>>[
              <String, dynamic>{
                'kind': 'MEMORY_SOURCE',
                'id': '22222222-2222-4222-8222-222222222222',
                'source_type': 'USER_TEXT',
                'memory_source_id': '33333333-3333-4333-8333-333333333333',
                'occurred_at': '2026-09-19T03:00:00Z',
                'confidence': 1.0,
                'excerpt': content,
              },
            ]
          : <Map<String, dynamic>>[],
    };
  }

  @override
  Future<Map<String, dynamic>> getProfile() async => <String, dynamic>{
        'id': owner,
        'nickname': '引导测试用户',
        'email': 'onboarding@example.test',
        'timezone': 'Asia/Shanghai',
        'locale': 'zh-CN',
      };

  @override
  Future<Map<String, dynamic>> getPrivacyStatus() async => <String, dynamic>{
        'recording_paused': false,
        'paused_until': null,
      };
}

Future<void> _pumpUntil(
  WidgetTester tester,
  bool Function() condition, {
  String reason = 'condition was not reached',
  int maxFrames = 120,
}) async {
  for (var frame = 0; frame < maxFrames; frame += 1) {
    await tester.pump(const Duration(milliseconds: 50));
    if (condition()) return;
  }
  throw TestFailure('Timed out waiting for onboarding test state: $reason');
}

void main() {
  sqfliteFfiInit();
  final factory = databaseFactoryFfiNoIsolate;

  late Directory tempDirectory;
  late String databasePath;
  late OfflineQueueStore queue;
  late _OnboardingApi api;
  late _MemoryOnboardingStore onboarding;

  setUp(() async {
    tempDirectory = await Directory.systemTemp.createTemp('jiyidashi-onboarding-app-');
    databasePath = '${tempDirectory.path}${Platform.pathSeparator}offline.sqlite3';
    queue = OfflineQueueStore(
      factory: factory,
      databasePathProvider: () async => databasePath,
    );
    api = _OnboardingApi();
    onboarding = _MemoryOnboardingStore();
  });

  tearDown(() async {
    await queue.close();
    await factory.deleteDatabase(databasePath);
    if (await tempDirectory.exists()) {
      await tempDirectory.delete(recursive: true);
    }
  });

  Future<void> pumpShell(
    WidgetTester tester, {
    required bool startOnboarding,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: AppShell(
          api: api,
          offlineQueue: queue,
          onboardingStore: onboarding,
          startOnboarding: startOnboarding,
          onLogout: () {},
        ),
      ),
    );
    await tester.pumpAndSettle();
  }


  testWidgets('successful registration auto-starts onboarding from the real auth page', (
    tester,
  ) async {
    final authApi = _AuthenticationApi();
    final store = _MemoryOnboardingStore();
    await tester.pumpWidget(
      JiYiApp(
        api: authApi,
        offlineQueue: _ZeroQueue(),
        onboardingStore: store,
      ),
    );

    await tester.tap(find.text('第一次使用？创建账号'));
    await tester.pump();
    final fields = find.byType(TextField);
    expect(fields, findsNWidgets(3));
    await tester.enterText(fields.at(0), 'new@example.test');
    await tester.enterText(fields.at(1), 'example-password-123');
    await tester.enterText(fields.at(2), '新用户');
    await tester.tap(find.widgetWithText(FilledButton, '创建账号'));
    await _pumpUntil(
      tester,
      () => find.byKey(const ValueKey('onboarding-intro')).evaluate().isNotEmpty,
      reason: 'registration-triggered onboarding intro',
    );

    expect(find.byKey(const ValueKey('onboarding-intro')), findsOneWidget);
    expect(store.values[owner], OnboardingStatus.inProgress);
  });

  testWidgets('ordinary login never infers a missing local row means new user', (
    tester,
  ) async {
    final authApi = _AuthenticationApi();
    final store = _MemoryOnboardingStore();
    await tester.pumpWidget(
      JiYiApp(
        api: authApi,
        offlineQueue: _ZeroQueue(),
        onboardingStore: store,
      ),
    );

    final fields = find.byType(TextField);
    expect(fields, findsNWidgets(2));
    await tester.enterText(fields.at(0), 'existing@example.test');
    await tester.enterText(fields.at(1), 'example-password-123');
    await tester.tap(find.widgetWithText(FilledButton, '登录'));
    await _pumpUntil(
      tester,
      () => find.text('今天').evaluate().isNotEmpty,
      reason: 'ordinary login Today page',
    );

    expect(find.byKey(const ValueKey('onboarding-intro')), findsNothing);
    expect(find.text('今天'), findsWidgets);
    expect(store.values[owner], isNull);
  });

  testWidgets('existing user with no local onboarding row is never trapped', (tester) async {
    await pumpShell(tester, startOnboarding: false);

    expect(find.text('今天'), findsWidgets);
    expect(find.byKey(const ValueKey('onboarding-intro')), findsNothing);
    expect(onboarding.values[owner], isNull);
  });

  testWidgets('real capture then real evidence completes the Aha flow', (tester) async {
    await pumpShell(tester, startOnboarding: true);

    expect(find.byKey(const ValueKey('onboarding-intro')), findsOneWidget);
    expect(onboarding.values[owner], OnboardingStatus.inProgress);
    expect(find.textContaining('不会申请后台定位'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('onboarding-start')));
    await _pumpUntil(
      tester,
      () => find.textContaining('第 1 步').evaluate().isNotEmpty,
      reason: 'capture onboarding step',
    );
    expect(find.textContaining('第 1 步'), findsOneWidget);

    const memory = '周五下午三点去公司前台取合同';
    final contentField = find.byKey(const ValueKey('capture-text-content'));
    await tester.ensureVisible(contentField);
    await tester.enterText(contentField, memory);
    final submit = find.byKey(const ValueKey('capture-text-submit'));
    await tester.ensureVisible(submit);
    await tester.tap(submit);
    await _pumpUntil(
      tester,
      () => find.textContaining('第 2 步').evaluate().isNotEmpty,
      reason: 'authoritative saved Memory to retrieval step',
    );

    expect(api.savedContent, memory);
    expect(find.textContaining('第 2 步'), findsOneWidget);

    final queryInput = tester.widget<TextField>(
      find.byKey(const ValueKey('memory-query-input')),
    );
    expect(queryInput.controller?.text, memory);

    final queryButton = find.byKey(const ValueKey('memory-query-submit'));
    await tester.ensureVisible(queryButton);
    await tester.tap(queryButton);
    await _pumpUntil(
      tester,
      () => find.textContaining('第 3 步').evaluate().isNotEmpty,
      reason: 'query returned target Memory with Evidence',
    );

    expect(api.queriedQuestion, memory);
    expect(find.textContaining('第 3 步'), findsOneWidget);
    expect(find.text('为什么这么回答'), findsOneWidget);
    expect(find.textContaining('用户文字记录'), findsOneWidget);
    expect(onboarding.values[owner], OnboardingStatus.inProgress);

    final complete = find.byKey(const ValueKey('onboarding-complete'));
    await tester.ensureVisible(complete);
    await tester.tap(complete);
    await _pumpUntil(
      tester,
      () => onboarding.values[owner] == OnboardingStatus.completed &&
          find.byType(OnboardingGuideBar).evaluate().isEmpty,
      reason: 'persisted onboarding completion',
    );

    expect(onboarding.values[owner], OnboardingStatus.completed);
    expect(find.byType(OnboardingGuideBar), findsNothing);
    expect(find.text('为什么这么回答'), findsOneWidget);
  });


  testWidgets('evidence for another memory cannot satisfy the onboarding retrieval step', (
    tester,
  ) async {
    await pumpShell(tester, startOnboarding: true);
    await tester.tap(find.byKey(const ValueKey('onboarding-start')));
    await _pumpUntil(
      tester,
      () => find.textContaining('第 1 步').evaluate().isNotEmpty,
      reason: 'capture step before unrelated-evidence regression',
    );

    const memory = '刚保存的唯一引导记忆';
    final contentField = find.byKey(const ValueKey('capture-text-content'));
    await tester.ensureVisible(contentField);
    await tester.enterText(contentField, memory);
    final submit = find.byKey(const ValueKey('capture-text-submit'));
    await tester.ensureVisible(submit);
    await tester.tap(submit);
    await _pumpUntil(
      tester,
      () => find.textContaining('第 2 步').evaluate().isNotEmpty,
      reason: 'retrieval step before unrelated-evidence regression',
    );

    api.queryMemoryId = '99999999-9999-4999-8999-999999999999';
    final queryButton = find.byKey(const ValueKey('memory-query-submit'));
    await tester.ensureVisible(queryButton);
    await tester.tap(queryButton);
    await _pumpUntil(
      tester,
      () => find.text('为什么这么回答').evaluate().isNotEmpty,
      reason: 'unrelated Evidence rendered without advancing step',
    );

    expect(find.textContaining('第 2 步'), findsOneWidget);
    expect(find.text('为什么这么回答'), findsOneWidget);
    expect(find.byKey(const ValueKey('onboarding-complete')), findsNothing);
  });

  testWidgets('skip persists and profile provides deterministic re-entry', (tester) async {
    await pumpShell(tester, startOnboarding: true);

    await tester.tap(find.byKey(const ValueKey('onboarding-skip-intro')));
    await _pumpUntil(
      tester,
      () => onboarding.values[owner] == OnboardingStatus.skipped &&
          find.byKey(const ValueKey('onboarding-intro')).evaluate().isEmpty,
      reason: 'persisted skip',
    );
    expect(onboarding.values[owner], OnboardingStatus.skipped);
    expect(find.byKey(const ValueKey('onboarding-intro')), findsNothing);

    await tester.tap(find.text('我的'));
    await _pumpUntil(
      tester,
      () => find
          .byKey(const ValueKey('profile-restart-onboarding'))
          .evaluate()
          .isNotEmpty,
      reason: 'profile onboarding re-entry',
    );
    final restart = find.byKey(const ValueKey('profile-restart-onboarding'));
    await tester.ensureVisible(restart);
    await tester.tap(restart);
    await _pumpUntil(
      tester,
      () => onboarding.values[owner] == OnboardingStatus.inProgress &&
          find.byKey(const ValueKey('onboarding-intro')).evaluate().isNotEmpty,
      reason: 'restarted onboarding intro',
    );

    expect(onboarding.values[owner], OnboardingStatus.inProgress);
    expect(find.byKey(const ValueKey('onboarding-intro')), findsOneWidget);
  });

  testWidgets('intro remains scrollable on a small phone viewport', (tester) async {
    tester.view.physicalSize = const Size(320, 480);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    await tester.pumpWidget(
      MaterialApp(
        theme: JiYiTheme.light(),
        home: Scaffold(
          body: SafeArea(
            child: OnboardingIntroPage(onStart: () {}, onSkip: () {}),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(tester.takeException(), isNull);
    expect(find.byKey(const ValueKey('onboarding-intro')), findsOneWidget);
    await tester.ensureVisible(find.byKey(const ValueKey('onboarding-start')));
    expect(tester.takeException(), isNull);
  });
}
