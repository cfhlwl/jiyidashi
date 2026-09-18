import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/offline_sync.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const userA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const userB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

typedef TextHandler = Future<Map<String, dynamic>> Function(
  String? title,
  String content,
  DateTime? occurredAt,
  String? clientUuid,
);
typedef ObjectHandler = Future<Map<String, dynamic>> Function(
  String objectName,
  String locationText,
  DateTime? recordedAt,
  String? clientUuid,
);

class _SyncApi extends JiYiApiClient {
  _SyncApi({required String userId})
      : super(baseUrl: 'https://example.invalid/v1') {
    authenticatedUserId = userId;
    accessToken = 'test-token';
  }

  TextHandler? textHandler;
  ObjectHandler? objectHandler;
  int textCalls = 0;
  int objectCalls = 0;
  final List<String?> textKeys = [];
  final List<String?> objectKeys = [];
  final List<DateTime?> textOccurredAts = [];
  final List<DateTime?> objectRecordedAts = [];

  @override
  Future<Map<String, dynamic>> createTextMemory({
    String? title,
    required String content,
    DateTime? occurredAt,
    String? clientUuid,
  }) async {
    textCalls += 1;
    textKeys.add(clientUuid);
    textOccurredAts.add(occurredAt);
    final handler = textHandler;
    if (handler == null) return {'id': 'memory-$textCalls'};
    return handler(title, content, occurredAt, clientUuid);
  }

  @override
  Future<Map<String, dynamic>> rememberObjectLocation({
    required String objectName,
    required String locationText,
    DateTime? recordedAt,
    String? clientUuid,
  }) async {
    objectCalls += 1;
    objectKeys.add(clientUuid);
    objectRecordedAts.add(recordedAt);
    final handler = objectHandler;
    if (handler == null) return {'id': 'location-$objectCalls'};
    return handler(objectName, locationText, recordedAt, clientUuid);
  }
}

void main() {
  sqfliteFfiInit();
  final factory = databaseFactoryFfiNoIsolate;
  late Directory tempDirectory;
  late String databasePath;
  late OfflineQueueStore store;

  setUp(() async {
    tempDirectory = await Directory.systemTemp.createTemp('jiyidashi-sync-');
    databasePath = '${tempDirectory.path}${Platform.pathSeparator}sync.sqlite3';
    store = OfflineQueueStore(
      factory: factory,
      databasePathProvider: () async => databasePath,
    );
  });

  tearDown(() async {
    await store.close();
    await factory.deleteDatabase(databasePath);
    if (await tempDirectory.exists()) {
      await tempDirectory.delete(recursive: true);
    }
  });

  test('response loss retries the same client UUID and completes once', () async {
    // 第一次请求模拟“服务端已提交但响应丢失”；
    // 客户端只能把同一个 SQLite client_uuid 再发一次，并以第二次权威响应完成任务。
    final api = _SyncApi(userId: userA);
    var first = true;
    api.textHandler = (title, content, occurredAt, clientUuid) async {
      if (first) {
        first = false;
        throw TransportException('response lost after commit');
      }
      return {'id': 'authoritative-memory-id'};
    };
    final sync = OfflineSyncCoordinator(api: api, store: store);
    final queued = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '11111111-1111-4111-8111-111111111111',
      content: '响应丢失也不能重复创建',
    );

    final firstReport = await sync.flush(userA);
    expect(firstReport.retryableFailures, 1);
    final failed = await store.findByClientUuid(userA, queued.clientUuid);
    expect(failed!.status, OfflineQueueStatus.failed);
    expect(failed.retryable, isTrue);

    final secondReport = await sync.flush(userA);
    expect(secondReport.completed, 1);
    final completed = await store.findByClientUuid(userA, queued.clientUuid);
    expect(completed!.status, OfflineQueueStatus.completed);
    expect(completed.serverResourceId, 'authoritative-memory-id');
    expect(completed.attemptCount, 2);
    expect(api.textCalls, 2);
    expect(api.textKeys, [queued.clientUuid, queued.clientUuid]);
  });

  test('concurrent flush calls share one active send', () async {
    // 生命周期 resumed 与用户手动同步同时触发时，
    // coordinator 必须共享同一个 active flush，不能把同一 outbox 行并发发送两次。
    final api = _SyncApi(userId: userA);
    final entered = Completer<void>();
    final release = Completer<void>();
    api.textHandler = (title, content, occurredAt, clientUuid) async {
      if (!entered.isCompleted) entered.complete();
      await release.future;
      return {'id': 'single-flight-memory'};
    };
    final sync = OfflineSyncCoordinator(api: api, store: store);
    await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '22222222-2222-4222-8222-222222222222',
      content: '只允许发送一次',
    );

    final firstFlush = sync.flush(userA);
    await entered.future;
    final secondFlush = sync.flush(userA);
    release.complete();
    final reports = await Future.wait([firstFlush, secondFlush]);

    expect(api.textCalls, 1);
    expect(reports[0].completed, 1);
    expect(reports[1].completed, 1);
  });

  test('cancelled task is never sent by automatic flush', () async {
    final api = _SyncApi(userId: userA);
    final sync = OfflineSyncCoordinator(api: api, store: store);
    final queued = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '33333333-3333-4333-8333-333333333333',
      content: '取消后不能复活',
    );
    await store.cancel(userA, queued.clientUuid);

    final report = await sync.flush(userA);
    expect(report.attempted, 0);
    expect(api.textCalls, 0);
    expect(
      (await store.findByClientUuid(userA, queued.clientUuid))!.status,
      OfflineQueueStatus.cancelled,
    );
  });

  test('HTTP and protocol failures are blocked from automatic retry', () async {
    final api = _SyncApi(userId: userA);
    final sync = OfflineSyncCoordinator(api: api, store: store);

    api.textHandler = (title, content, occurredAt, clientUuid) async {
      throw ApiException(422, '内容不符合要求');
    };
    final httpTask = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '44444444-4444-4444-8444-444444444444',
      content: 'HTTP 失败',
    );
    final first = await sync.flush(userA);
    expect(first.blockedFailures, 1);
    final httpFailed = await store.findByClientUuid(userA, httpTask.clientUuid);
    expect(httpFailed!.retryable, isFalse);
    expect(api.textCalls, 1);

    await sync.flush(userA);
    expect(api.textCalls, 1);

    api.textHandler = (title, content, occurredAt, clientUuid) async {
      throw ProtocolException('服务端返回格式不正确');
    };
    final protocolTask = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '55555555-5555-4555-8555-555555555555',
      content: '协议失败',
    );
    final second = await sync.flush(userA);
    expect(second.blockedFailures, 1);
    final protocolFailed =
        await store.findByClientUuid(userA, protocolTask.clientUuid);
    expect(protocolFailed!.retryable, isFalse);
    expect(api.textCalls, 2);

    await sync.flush(userA);
    expect(api.textCalls, 2);
  });

  test('503 stays retryable and succeeds on a later flush with the same key', () async {
    final api = _SyncApi(userId: userA);
    var first = true;
    api.textHandler = (title, content, occurredAt, clientUuid) async {
      if (first) {
        first = false;
        throw ApiException(503, 'temporary outage');
      }
      return {'id': 'recovered-memory'};
    };
    final sync = OfflineSyncCoordinator(api: api, store: store);
    final queued = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '56565656-5656-4656-8656-565656565656',
      content: '503 不能永久卡死',
    );

    final firstReport = await sync.flush(userA);
    expect(firstReport.retryableFailures, 1);
    expect(
      (await store.findByClientUuid(userA, queued.clientUuid))!.retryable,
      isTrue,
    );
    final secondReport = await sync.flush(userA);
    expect(secondReport.completed, 1);
    expect(api.textKeys, [queued.clientUuid, queued.clientUuid]);
  });

  test('401 stops the current flush and keeps the task retryable', () async {
    final api = _SyncApi(userId: userA);
    api.textHandler = (title, content, occurredAt, clientUuid) async {
      throw ApiException(401, 'expired');
    };
    final sync = OfflineSyncCoordinator(api: api, store: store);
    final first = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '57575757-5757-4757-8757-575757575757',
      content: '认证失败后等待重新登录',
    );
    final second = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '58585858-5858-4858-8858-585858585858',
      content: '后续任务不能继续发送',
    );

    final report = await sync.flush(userA);
    expect(report.attempted, 1);
    expect(report.retryableFailures, 1);
    expect((await store.findByClientUuid(userA, first.clientUuid))!.retryable, isTrue);
    expect(
      (await store.findByClientUuid(userA, second.clientUuid))!.status,
      OfflineQueueStatus.pending,
    );
  });

  test('429 is retryable and defers later tasks to the next trigger', () async {
    final api = _SyncApi(userId: userA);
    api.textHandler = (title, content, occurredAt, clientUuid) async {
      throw ApiException(429, 'rate limited');
    };
    final sync = OfflineSyncCoordinator(api: api, store: store);
    await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '59595959-5959-4959-8959-595959595959',
      content: '限流后稍后再试',
    );
    final second = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '60606060-6060-4060-8060-606060606060',
      content: '限流后不继续打服务器',
    );

    final report = await sync.flush(userA);
    expect(report.attempted, 1);
    expect(report.retryableFailures, 1);
    expect(
      (await store.findByClientUuid(userA, second.clientUuid))!.status,
      OfflineQueueStatus.pending,
    );
  });

  test('flush only consumes the authenticated owner queue', () async {
    final api = _SyncApi(userId: userA);
    final sync = OfflineSyncCoordinator(api: api, store: store);
    await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '66666666-6666-4666-8666-666666666666',
      content: 'A 的记录',
    );
    final b = await store.enqueueTextMemory(
      ownerUserId: userB,
      clientUuid: '77777777-7777-4777-8777-777777777777',
      content: 'B 的记录',
    );

    final report = await sync.flush(userA);
    expect(report.completed, 1);
    expect(api.textCalls, 1);
    expect(
      (await store.findByClientUuid(userB, b.clientUuid))!.status,
      OfflineQueueStatus.pending,
    );
    expect(await store.listDeliverable(userB), hasLength(1));
  });

  test('object location keeps its original recorded_at across delayed flush', () async {
    final api = _SyncApi(userId: userA);
    final sync = OfflineSyncCoordinator(api: api, store: store);
    final recordedAt = DateTime.utc(2026, 9, 17, 2);
    final queued = await store.enqueueObjectLocation(
      ownerUserId: userA,
      clientUuid: '88888888-8888-4888-8888-888888888888',
      objectName: '护照',
      locationText: '书房左侧柜子第二层',
      recordedAt: recordedAt,
    );

    final report = await sync.flush(userA);
    expect(report.completed, 1);
    expect(api.objectCalls, 1);
    expect(api.objectKeys, [queued.clientUuid]);
    expect(api.objectRecordedAts, [recordedAt]);
    expect(queued.payload['recorded_at'], recordedAt.toIso8601String());
    final completed = await store.findByClientUuid(userA, queued.clientUuid);
    expect(completed!.serverResourceId, 'location-1');
  });

  test('text memory keeps its original occurred_at across response-loss retry', () async {
    final api = _SyncApi(userId: userA);
    var first = true;
    api.textHandler = (title, content, occurredAt, clientUuid) async {
      if (first) {
        first = false;
        throw TransportException('response lost');
      }
      return {'id': 'stable-time-memory'};
    };
    final sync = OfflineSyncCoordinator(api: api, store: store);
    final occurredAt = DateTime.utc(2026, 9, 17, 1, 30);
    final queued = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '89898989-8989-4989-8989-898989898989',
      content: '发生时间不能漂到同步时刻',
      occurredAt: occurredAt,
    );

    await sync.flush(userA);
    await sync.flush(userA);

    expect(api.textOccurredAts, [occurredAt, occurredAt]);
    expect(queued.payload['occurred_at'], occurredAt.toIso8601String());
  });

  test('object location reuses one immutable auth token across both HTTP requests', () async {
    late JiYiApiClient api;
    var requestCount = 0;
    final client = MockClient((request) async {
      requestCount += 1;
      expect(request.headers['authorization'], 'Bearer token-a');
      if (requestCount == 1) {
        api.logout();
        api.accessToken = 'token-b';
        api.authenticatedUserId = userB;
        return http.Response(
          '{"id":"11111111-2222-4333-8444-555555555555","name":"护照"}',
          201,
          headers: {'content-type': 'application/json'},
        );
      }
      return http.Response(
        '{"id":"66666666-7777-4888-8999-000000000000","object_id":"11111111-2222-4333-8444-555555555555","location_text":"旧抽屉","recorded_at":"2026-09-17T02:00:00Z","confidence":1.0,"status":"STALE","memory_id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"}',
        201,
        headers: {'content-type': 'application/json'},
      );
    });
    api = JiYiApiClient(httpClient: client, baseUrl: 'https://example.invalid/v1')
      ..accessToken = 'token-a'
      ..authenticatedUserId = userA;

    final result = await api.rememberObjectLocation(
      objectName: '护照',
      locationText: '旧抽屉',
      recordedAt: DateTime.utc(2026, 9, 17, 2),
      clientUuid: '61616161-6161-4161-8161-616161616161',
    );

    expect(requestCount, 2);
    expect(result['id'], '66666666-7777-4888-8999-000000000000');
    expect(api.authenticatedUserId, userB);
  });

  test('auth session change stops later tasks in the same flush', () async {
    // 已发出的 A 请求可以写回 A 的原行；
    // 一旦登录会话版本改变，后续 A outbox 不能继续借用新账号会话发送。
    final api = _SyncApi(userId: userA);
    var calls = 0;
    api.textHandler = (title, content, occurredAt, clientUuid) async {
      calls += 1;
      if (calls == 1) {
        api.logout();
      }
      return {'id': 'memory-$calls'};
    };
    final sync = OfflineSyncCoordinator(api: api, store: store);
    await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: '99999999-9999-4999-8999-999999999999',
      content: '第一条',
    );
    final second = await store.enqueueTextMemory(
      ownerUserId: userA,
      clientUuid: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
      content: '第二条',
    );

    final report = await sync.flush(userA);
    expect(report.completed, 1);
    expect(api.textCalls, 1);
    expect(
      (await store.findByClientUuid(userA, second.clientUuid))!.status,
      OfflineQueueStatus.pending,
    );
  });
}
