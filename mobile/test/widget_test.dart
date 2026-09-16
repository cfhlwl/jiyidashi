import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/main.dart';

void main() {
  testWidgets('shows formal authentication before personal memory space', (tester) async {
    await tester.pumpWidget(const JiYiApp());

    // [人工注释][S1-001] 未登录用户必须先看到正式认证入口，不能直接进入个人记忆空间。
    expect(find.text('迹忆'), findsOneWidget);
    expect(find.text('登录'), findsOneWidget);
    expect(find.text('第一次使用？创建账号'), findsOneWidget);
    expect(find.text('今天'), findsNothing);
  });
}
