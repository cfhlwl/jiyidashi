import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/stage1_app.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

// [人工注释][S1-016] UI 回归用可控 API 故障区分“连接层离线”与“服务端明确拒绝”，防止把真实 4xx/5xx 伪装成本地成功。
class _CaptureApi extends JiYiApiClient {
  _CaptureApi(this.failure) : super(baseUrl: 'https://example.invalid/v1');

  final Object failure;

  @override
  Future<Map<String, dynamic>> createTextMemory({
    String? title,
    required String content,
  }) async {
    throw failure;
  }
}

void main() {
  sqfliteFfiInit();

  late Directory tempDirectory;
  late String databasePath;
  late OfflineQueueStore queue;

  // [人工注释][S1-015] Widget 测试也落真实临时 SQLite 文件，确保 UI 提示建立在持久化成功而不是 mock 内存对象之上。
  setUp(() async {
    tempDirectory = await Directory.systemTemp.createTemp('jiyidashi-capture-');
    databasePath =
        '${tempDirectory.path}${Platform.pathSeparator}offline-queue.sqlite3';
    queue = OfflineQueueStore(
      factory: databaseFactoryFfi,
      databasePathProvider: () async => databasePath,
      clientUuidFactory: () => '77777777-7777-4777-8777-777777777777',
    );
  });

  tearDown(() async {
    await queue.close();
    await databaseFactoryFfi.deleteDatabase(databasePath);
    if (await tempDirectory.exists()) {
      await tempDirectory.delete(recursive: true);
    }
  });

  Future<void> pumpCapture(
    WidgetTester tester,
    JiYiApiClient api,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CapturePage(api: api, offlineQueue: queue),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('connection failure persists text locally before success UI',
      (tester) async {
    // [人工注释][S1-015] 网络异常时只有 SQLite insert 完成后才允许显示“已保存到本机”，并清空用户输入。
    await pumpCapture(tester, _CaptureApi(Exception('network down')));
    final fields = find.byType(TextField);
    await tester.enterText(fields.at(0), '离线标题');
    await tester.enterText(fields.at(1), '离线时也不能丢的内容');
    await tester.tap(find.widgetWithText(FilledButton, '帮我记住'));
    await tester.pumpAndSettle();

    expect(find.textContaining('✓ 已保存到本机，待联网后发送'), findsOneWidget);
    expect(find.text('本机待发送'), findsOneWidget);
    expect(find.textContaining('有 1 条记录已安全保存在本机'), findsOneWidget);

    final all = await queue.listAll();
    expect(all, hasLength(1));
    expect(all.single.status, OfflineQueueStatus.pending);
    expect(all.single.payload['title'], '离线标题');
    expect(all.single.payload['content'], '离线时也不能丢的内容');
  });

  testWidgets('server ApiException remains a failure and is not queued',
      (tester) async {
    // [人工注释][S1-016] 服务端 422 等明确响应说明请求已到服务端；本地队列不得吞掉错误或显示离线保存成功。
    await pumpCapture(tester, _CaptureApi(ApiException(422, '内容不符合要求')));
    final fields = find.byType(TextField);
    await tester.enterText(fields.at(1), '这条记录被服务端拒绝');
    await tester.tap(find.widgetWithText(FilledButton, '帮我记住'));
    await tester.pumpAndSettle();

    expect(find.text('操作失败：内容不符合要求'), findsOneWidget);
    expect(find.textContaining('已保存到本机'), findsNothing);
    expect(await queue.countAwaitingDelivery(), 0);
    expect(await queue.listAll(), isEmpty);
  });
}
