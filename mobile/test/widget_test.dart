import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/main.dart';

void main() {
  testWidgets('renders the main navigation', (tester) async {
    await tester.pumpWidget(const JiYiApp());
    expect(find.text('今天'), findsWidgets);
    expect(find.text('时间轴'), findsOneWidget);
    expect(find.text('记一下'), findsOneWidget);
    expect(find.text('问记忆'), findsOneWidget);
    expect(find.text('我的'), findsOneWidget);
  });
}
