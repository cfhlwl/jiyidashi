import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';
import 'package:jiyidashi/main.dart';

void main() {
  testWidgets('shows formal authentication before personal memory space', (tester) async {
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: MemoryAuthSessionStore(),
    );
    await tester.pumpWidget(JiYiApp(api: api));
    await tester.pumpAndSettle();

    // Cold start resolves server-authoritative restore before showing the formal auth
    // entry. With no persisted refresh session, personal owner UI must stay hidden.
    expect(find.bySemanticsLabel('迹忆'), findsOneWidget);
    expect(find.text('邮箱登录'), findsOneWidget);
    expect(find.text('第一次使用？创建账号'), findsOneWidget);
    expect(find.text('今天'), findsNothing);
  });
}
