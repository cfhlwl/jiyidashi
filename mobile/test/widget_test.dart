import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';
import 'package:jiyidashi/main.dart';

class _ControlledRestoreApi extends JiYiApiClient {
  _ControlledRestoreApi(this.restoreResult)
      : super(
          baseUrl: 'https://example.test/v1',
          sessionStore: MemoryAuthSessionStore(),
        );

  final Future<AuthRestoreStatus> restoreResult;
  int restoreCallCount = 0;

  @override
  Future<AuthRestoreStatus> restorePersistedSession() {
    restoreCallCount += 1;
    return restoreResult;
  }
}

void main() {
  testWidgets('shows formal authentication before personal memory space', (tester) async {
    final restore = Completer<AuthRestoreStatus>();
    final api = _ControlledRestoreApi(restore.future);

    await tester.pumpWidget(JiYiApp(api: api));
    await tester.pump();

    // Cold start must remain neutral while the server-authoritative restore is pending.
    expect(api.restoreCallCount, 1);
    expect(find.bySemanticsLabel('迹忆'), findsOneWidget);
    expect(find.text('邮箱登录'), findsNothing);
    expect(find.text('今天'), findsNothing);

    // Resolve the same transition explicitly; do not depend on wall-clock timing or
    // the real session store to make the signed-out state observable.
    restore.complete(AuthRestoreStatus.noPersistedSession);
    await tester.pump();
    await tester.pumpAndSettle();

    expect(find.bySemanticsLabel('迹忆'), findsOneWidget);
    expect(find.text('邮箱登录'), findsOneWidget);
    expect(find.text('第一次使用？创建账号'), findsOneWidget);
    expect(find.text('今天'), findsNothing);
  });
}
