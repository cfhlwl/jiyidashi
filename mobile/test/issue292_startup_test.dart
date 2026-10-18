import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/main.dart' as entry;

void main() {
  for (final platform in <TargetPlatform>[TargetPlatform.android, TargetPlatform.iOS]) {
    testWidgets('Issue #292: entrypoint can schedule visible first frame without map key on $platform',
        (tester) async {
      debugDefaultTargetPlatformOverride = platform;
      addTearDown(() => debugDefaultTargetPlatformOverride = null);

      Widget? captured;
      entry.startJiYiApp(
        app: const MaterialApp(home: Scaffold(body: Text('迹忆登录入口'))),
        runner: (widget) => captured = widget,
      );
      expect(captured, isNotNull);
      await tester.pumpWidget(captured!);
      expect(find.text('迹忆登录入口'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
