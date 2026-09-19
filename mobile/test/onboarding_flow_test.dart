import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/onboarding_flow.dart';
import 'package:jiyidashi/onboarding_state.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';

// [人工注释][S1-026] 验证注册触发、真实保存、目标 Memory 找回、Evidence、跳过与重新进入的完整闭环。

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


class _MemoryQueue extends OfflineQueueStore {
  OfflineQueueItem? _item;
  var _nextId = 1;

  OfflineQueueItem _copy(
    OfflineQueueItem source, {
    OfflineQueueStatus? status,
    int? attemptCount,
    bool? retryable,
    String? lastError,
    String? serverResourceId,
    DateTime? completedAt,
  }) {
    return OfflineQueueItem(
      id: source.id,
      ownerUserId: source.ownerUserId,
      clientUuid: source.clientUuid,
      operationType: source.operationType,
      payload: source.payload,
      status: status ?? source.status,
      attemptCount: attemptCount ?? source.attemptCount,
      retryable: retryable ?? source.retryable,
      lastError: lastError,
      serverResourceId: serverResourceId,
      createdAt: source.createdAt,
      updatedAt: DateTime.utc(2026, 9, 19, 4),
      completedAt: completedAt,
      cancelledAt: source.cancelledAt,
    );
  }

  @override
  Future<int> countAwaitingDelivery(String ownerUserId) async {
    final item = _item;
    if (item == null || item.ownerUserId != ownerUserId || item.isTerminal) return 0;
    return 1;
  }

  @override
  Future<OfflineQueueItem> enqueueTextMemory({
    required String ownerUserId,
    String? title,
    required String content,
    DateTime? occurredAt,
    String? clientUuid,
  }) async {
    final now = occurredAt?.toUtc() ?? DateTime.utc(2026, 9, 19, 3);
    final item = OfflineQueueItem(
      id: _nextId++,
      ownerUserId: ownerUserId,
      clientUuid: clientUuid ?? '44444444-4444-4444-8444-444444444444',
      operationType: OfflineQueueStore.textMemoryOperation,
      payload: <String, dynamic>{
        if (title != null && title.trim().isNotEmpty) 'title': title.trim(),
        'content': content.trim(),
        'occurred_at': now.toIso8601String(),
      },
      status: OfflineQueueStatus.pending,
      attemptCount: 0,
      retryable: true,
      createdAt: now,
      updatedAt: now,
    );
    _item = item;
    return item;
  }

  @override
  Future<List<OfflineQueueItem>> listDeliverable(String ownerUserId) async {
    final item = _item;
    if (item == null || item.ownerUserId != ownerUserId) return const [];
    if (item.status == OfflineQueueStatus.pending ||
        (item.status == OfflineQueueStatus.failed && item.retryable)) {
      return <OfflineQueueItem>[item];
    }
    return const [];
  }

  @override
  Future<OfflineQueueItem?> findByClientUuid(
    String ownerUserId,
    String clientUuid,
  ) async {
    final item = _item;
    if (item == null ||
        item.ownerUserId != ownerUserId ||
        item.clientUuid != clientUuid) {
      return null;
    }
    return item;
  }

  @override
  Future<OfflineQueueItem> markSending(
    String ownerUserId,
    String clientUuid,
  ) async {
    final item = await findByClientUuid(ownerUserId, clientUuid);
    if (item == null) throw StateError('queue item missing');
    final next = _copy(
      item,
      status: OfflineQueueStatus.sending,
      attemptCount: item.attemptCount + 1,
      retryable: true,
    );
    _item = next;
    return next;
  }

  @override
  Future<OfflineQueueItem> markCompleted(
    String ownerUserId,
    String clientUuid, {
    required String serverResourceId,
  }) async {
    final item = await findByClientUuid(ownerUserId, clientUuid);
    if (item == null) throw StateError('queue item missing');
    final next = _copy(
      item,
      status: OfflineQueueStatus.completed,
      retryable: false,
      serverResourceId: serverResourceId,
      completedAt: DateTime.utc(2026, 9, 19, 4),
    );
    _item = next;
    return next;
  }

  @override
  Future<OfflineQueueItem> markFailed(
    String ownerUserId,
    String clientUuid,
    String error, {
    required bool retryable,
  }) async {
    final item = await findByClientUuid(ownerUserId, clientUuid);
    if (item == null) throw StateError('queue item missing');
    final next = _copy(
      item,
      status: OfflineQueueStatus.failed,
      retryable: retryable,
      lastError: error,
    );
    _item = next;
    return next;
  }

  @override
  Future<OfflineQueueItem> retryFailed(
    String ownerUserId,
    String clientUuid,
  ) async {
    final item = await findByClientUuid(ownerUserId, clientUuid);
    if (item == null) throw StateError('queue item missing');
    final next = _copy(
      item,
      status: OfflineQueueStatus.pending,
      retryable: true,
    );
    _item = next;
    return next;
  }

  @override
  Future<void> close() async {}
}

// [人工注释][S1-026] Widget 流程只验证真实 AppShell/Capture/Query 编排；
// SQLite 驱动和重启持久化由 onboarding_state_test 单独覆盖，避免 Flutter FakeAsync 与 FFI 数据库互锁。
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
  late OfflineQueueStore queue;
  late _OnboardingApi api;
  late _MemoryOnboardingStore onboarding;

  setUp(() {
    queue = _MemoryQueue();
    api = _OnboardingApi();
    onboarding = _MemoryOnboardingStore();
  });

  tearDown(() async {
    await queue.close();
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
    await _pumpUntil(
      tester,
      () => startOnboarding
          ? find.byKey(const ValueKey('onboarding-intro')).evaluate().isNotEmpty
          : find.text('今天').evaluate().isNotEmpty,
      reason: startOnboarding ? 'onboarding intro' : 'normal Today page',
    );
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
    final titleField = find.byKey(const ValueKey('capture-text-title'));
    await tester.ensureVisible(titleField);
    await tester.enterText(titleField, '与正文完全不同的标题');
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
    // JiYiPageFrame 本身就是 Profile 的主 ListView；直接在它上面拖动到目标可点击，
    // 避免 Scrollable finder 误选到页面内部其他可滚动组件。
    final profileList = find.byType(ListView).first;
    await tester.dragUntilVisible(
      restart,
      profileList,
      const Offset(0, -240),
    );
    // dragUntilVisible 在目标“刚露出”时就会停止；再向上滚一小段，确保按钮中心进入可点击区域。
    await tester.drag(profileList, const Offset(0, -120));
    await tester.pump();
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
    final start = find.byKey(const ValueKey('onboarding-start'));
    await tester.scrollUntilVisible(
      start,
      160,
      scrollable: find.byType(Scrollable).first,
    );
    expect(start, findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
