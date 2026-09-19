import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/account_delete_section.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/stage1_app.dart';

const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

class _AccountDeleteApi extends JiYiApiClient {
  _AccountDeleteApi({this.transportFailureFirst = false})
      : super(baseUrl: 'https://account-delete.invalid/v1') {
    accessToken = 'delete-token';
    authenticatedUserId = owner;
  }

  final bool transportFailureFirst;
  final List<String> requestIds = <String>[];
  final List<bool> cleanupReady = <bool>[];
  int commitCalls = 0;

  @override
  Future<Map<String, dynamic>> deleteAccount({
    required String requestId,
    required bool localCleanupReady,
  }) async {
    requestIds.add(requestId);
    cleanupReady.add(localCleanupReady);
    if (!localCleanupReady) {
      return <String, dynamic>{
        'request_id': requestId,
        'data_deletion_status': null,
        'completed': false,
        'retry_after_seconds': null,
        'deleted_counts': <String, int>{},
      };
    }

    commitCalls += 1;
    if (transportFailureFirst && commitCalls == 1) {
      throw TransportException('synthetic response loss');
    }
    if (commitCalls == 1) {
      return <String, dynamic>{
        'request_id': requestId,
        'data_deletion_status': 'WAITING_STORAGE_QUIET',
        'completed': false,
        'retry_after_seconds': 3,
        'deleted_counts': <String, int>{},
      };
    }
    return <String, dynamic>{
      'request_id': requestId,
      'data_deletion_status': 'COMPLETED',
      'completed': true,
      'retry_after_seconds': null,
      'deleted_counts': <String, int>{},
    };
  }
}

class _RecoveryProfileApi extends _AccountDeleteApi {
  @override
  Future<Map<String, dynamic>> getProfile() async {
    throw ApiException(423, 'ACCOUNT_DELETION_IN_PROGRESS');
  }
}

class _RecoveryLoginApi extends JiYiApiClient {
  _RecoveryLoginApi() : super(baseUrl: 'https://recovery.invalid/v1');

  @override
  Future<Map<String, dynamic>> login({
    required String email,
    required String password,
  }) async {
    accessToken = 'recovery-token';
    authenticatedUserId = owner;
    return <String, dynamic>{
      'access_token': 'recovery-token',
      'token_type': 'bearer',
      'user_id': owner,
      'account_deletion_in_progress': true,
    };
  }
}

void main() {
  test('api client sends exact account-delete protocol confirmation', () async {
    var calls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      httpClient: MockClient((request) async {
        calls += 1;
        expect(request.method, 'POST');
        expect(request.url.path, '/v1/account/delete');
        expect(request.headers['authorization'], 'Bearer account-token');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(
          body['request_id'],
          '11111111-1111-4111-8111-111111111111',
        );
        expect(body['confirmation'], 'DELETE_MY_ACCOUNT');
        expect(body['local_cleanup_ready'], isFalse);
        return http.Response(
          jsonEncode({
            'request_id': body['request_id'],
            'data_deletion_status': 'COMPLETED',
            'completed': true,
            'retry_after_seconds': null,
            'deleted_counts': <String, int>{},
          }),
          200,
          headers: const {'content-type': 'application/json'},
        );
      }),
    );
    api.accessToken = 'account-token';
    api.authenticatedUserId = owner;

    final prepared = await api.deleteAccount(
      requestId: '11111111-1111-4111-8111-111111111111',
      localCleanupReady: false,
    );
    expect(prepared['completed'], isTrue);
    expect(calls, 1);
  });

  testWidgets('typed confirmation then 202 retry reuses one request id', (tester) async {
    final api = _AccountDeleteApi();
    var intentCallbacks = 0;
    var deletedCallbacks = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: AccountDeleteSection(
              api: api,
              onIntentConfirmed: () async {
                expect(api.cleanupReady, <bool>[false]);
                intentCallbacks += 1;
              },
              onDeleted: () async {
                deletedCallbacks += 1;
              },
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.byKey(const ValueKey('account-delete-open')));
    await tester.pumpAndSettle();

    final confirm = find.byKey(const ValueKey('account-delete-confirm-submit'));
    expect(tester.widget<FilledButton>(confirm).onPressed, isNull);
    await tester.enterText(
      find.byKey(const ValueKey('account-delete-confirm-input')),
      '注销账号',
    );
    await tester.pump();
    expect(tester.widget<FilledButton>(confirm).onPressed, isNotNull);

    await tester.tap(confirm);
    await tester.pumpAndSettle();

    expect(intentCallbacks, 1);
    expect(api.requestIds, hasLength(2));
    expect(api.cleanupReady, <bool>[false, true]);
    final stableRequestId = api.requestIds.first;
    expect(api.requestIds.every((value) => value == stableRequestId), isTrue);
    expect(find.textContaining('3 秒后继续注销'), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, '继续注销'), findsOneWidget);
    expect(deletedCallbacks, 0);

    await tester.tap(find.byKey(const ValueKey('account-delete-open')));
    await tester.pumpAndSettle();

    expect(api.requestIds, <String>[
      stableRequestId,
      stableRequestId,
      stableRequestId,
    ]);
    expect(api.cleanupReady, <bool>[false, true, true]);
    expect(intentCallbacks, 1);
    expect(deletedCallbacks, 1);
  });

  testWidgets('resume mode skips typed confirmation and prepares local deletion first',
      (tester) async {
    final api = _AccountDeleteApi();
    var prepared = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AccountDeleteSection(
            api: api,
            resumeInProgress: true,
            onIntentConfirmed: () async {
              prepared += 1;
            },
            onDeleted: () async {},
          ),
        ),
      ),
    );

    expect(find.widgetWithText(OutlinedButton, '继续注销'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('account-delete-open')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('account-delete-confirm-input')), findsNothing);
    expect(prepared, 1);
    expect(api.requestIds, hasLength(1));
    expect(api.cleanupReady, <bool>[true]);
  });

  testWidgets('local cleanup failure stops before COMMIT after durable PREPARE',
      (tester) async {
    final api = _AccountDeleteApi();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AccountDeleteSection(
            api: api,
            onIntentConfirmed: () async {
              throw StateError('local purge failed');
            },
            onDeleted: () async {},
          ),
        ),
      ),
    );

    await tester.tap(find.byKey(const ValueKey('account-delete-open')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('account-delete-confirm-input')),
      '注销账号',
    );
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('account-delete-confirm-submit')));
    await tester.pumpAndSettle();

    expect(api.requestIds, hasLength(1));
    expect(api.cleanupReady, <bool>[false]);
    expect(find.textContaining('账号已进入注销保护'), findsOneWidget);
    // [人工注释][S1-022-FIX-003] 本机 purge 失败后必须退出 busy，用户才能重试恢复。
    final retryButton = tester.widget<OutlinedButton>(
      find.byKey(const ValueKey('account-delete-open')),
    );
    expect(retryButton.onPressed, isNotNull);
    expect(find.text('继续注销'), findsOneWidget);
  });

  testWidgets('response-loss keeps the same account deletion intent', (tester) async {
    final api = _AccountDeleteApi(transportFailureFirst: true);
    var deletedCallbacks = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AccountDeleteSection(
            api: api,
            onIntentConfirmed: () async {},
            onDeleted: () async {
              deletedCallbacks += 1;
            },
          ),
        ),
      ),
    );

    await tester.tap(find.byKey(const ValueKey('account-delete-open')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('account-delete-confirm-input')),
      '注销账号',
    );
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('account-delete-confirm-submit')));
    await tester.pumpAndSettle();

    expect(find.textContaining('无法确认注销进度'), findsOneWidget);
    expect(api.requestIds, hasLength(2));
    expect(api.cleanupReady, <bool>[false, true]);
    final first = api.requestIds.first;
    expect(api.requestIds.every((value) => value == first), isTrue);

    await tester.tap(find.byKey(const ValueKey('account-delete-open')));
    await tester.pumpAndSettle();

    expect(api.requestIds, <String>[first, first, first]);
    expect(api.cleanupReady, <bool>[false, true, true]);
    expect(deletedCallbacks, 1);
  });
  testWidgets('login recovery flag routes authenticated session into deletion recovery',
      (tester) async {
    var recovered = 0;
    var authenticated = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: AuthPage(
          api: _RecoveryLoginApi(),
          onAccountDeletionRecovery: () => recovered += 1,
          onAuthenticated: () => authenticated += 1,
        ),
      ),
    );

    final fields = find.byType(TextField);
    await tester.enterText(fields.at(0), 'owner@example.test');
    await tester.enterText(fields.at(1), 'secret');
    await tester.tap(find.widgetWithText(FilledButton, '登录'));
    await tester.pumpAndSettle();

    expect(recovered, 1);
    expect(authenticated, 1);
  });

  testWidgets('profile exposes continue-delete UI when ordinary API is gated',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ProfilePage(
            api: _RecoveryProfileApi(),
            onLogout: () {},
            onAccountDeleteIntentConfirmed: () async {},
            onAccountDeleted: () async {},
            resumeAccountDeletion: true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('账号注销正在进行'), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, '继续注销'), findsOneWidget);
  });

}
