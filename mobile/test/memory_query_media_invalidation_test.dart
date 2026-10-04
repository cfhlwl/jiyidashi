import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/media_presentation_cache.dart';
import 'package:jiyidashi/stage1_app.dart';

const _owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const _memory = '11111111-1111-4111-8111-111111111111';
const _media = '22222222-2222-4222-8222-222222222222';
const _version =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

class _DeleteQueryApi extends JiYiApiClient {
  _DeleteQueryApi() : super(baseUrl: 'https://query-delete.invalid/v1') {
    accessToken = 'token';
    authenticatedUserId = _owner;
  }

  int deleteCalls = 0;

  @override
  Future<Map<String, dynamic>> queryMemory(String question) async =>
      <String, dynamic>{
        'answer': '找到了这张照片。',
        'can_answer': true,
        'certainty': 'confirmed',
        'reason': null,
        'intent': 'FIND_EVENT',
        'evidence': <Map<String, dynamic>>[
          <String, dynamic>{
            'kind': 'PHOTO',
            'source_type': 'USER_PHOTO',
            'excerpt': '测试照片',
            'occurred_at': '2026-10-04T08:00:00Z',
          },
        ],
        'memory_ids': <String>[_memory],
        'day_footprint': null,
      };

  @override
  Future<Map<String, dynamic>> getMemory(String memoryId) async =>
      <String, dynamic>{
        'id': _memory,
        'user_id': _owner,
        'memory_type': 'PHOTO',
        'title': '测试照片',
        'content': '测试照片',
        'occurred_at': '2026-10-04T08:00:00Z',
        'source_type': 'USER_PHOTO',
        'confidence': 1.0,
        'place_id': null,
        'latitude': null,
        'longitude': null,
        'is_confirmed': true,
        'metadata_json': <String, dynamic>{'media_id': _media},
        'edit_revision': 0,
        'edited_at': null,
        'created_at': '2026-10-04T08:00:00Z',
      };

  @override
  Future<void> deleteMemory(String memoryId) async {
    expect(memoryId, _memory);
    deleteCalls += 1;
  }
}

class _DeleteQueryProjectionFailureApi extends _DeleteQueryApi {
  @override
  Future<Map<String, dynamic>> getMemory(String memoryId) async {
    throw TransportException('projection unavailable');
  }
}

void main() {
  testWidgets('Memory Query delete invalidates the deleted photo cache',
      (tester) async {
    final root =
        await Directory.systemTemp.createTemp('jiyi-query-delete-cache-');
    addTearDown(() => root.delete(recursive: true));

    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    final cached = await cache.putBytes(
      ownerUserId: _owner,
      mediaId: _media,
      cacheVersion: _version,
      bytes: <int>[1, 2, 3],
    );
    cache.markAuthorityValidated(ownerUserId: _owner, mediaId: _media);

    final api = _DeleteQueryApi();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MemoryQueryPage(api: api, mediaCache: cache),
        ),
      ),
    );
    await tester.enterText(find.byType(TextField).first, '找照片');
    await tester.tap(find.text('从我的记录里找'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('删除最相关记忆'));
    await tester.pumpAndSettle();
    expect(find.text('删除这条记忆？'), findsOneWidget);

    await tester.tap(find.text('确认删除'));
    await tester.pumpAndSettle();

    expect(api.deleteCalls, 1);
    expect(await cached.exists(), isFalse);
    expect(
      await cache.lookup(ownerUserId: _owner, mediaId: _media),
      isNull,
    );
    expect(
      cache.hasFreshAuthorityLease(ownerUserId: _owner, mediaId: _media),
      isFalse,
    );
  });

  testWidgets(
      'Memory Query delete purges owner cache when deleted media projection is unavailable',
      (tester) async {
    final root =
        await Directory.systemTemp.createTemp('jiyi-query-delete-fallback-');
    addTearDown(() => root.delete(recursive: true));

    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    final first = await cache.putBytes(
      ownerUserId: _owner,
      mediaId: _media,
      cacheVersion: _version,
      bytes: <int>[1, 2, 3],
    );
    final second = await cache.putBytes(
      ownerUserId: _owner,
      mediaId: '33333333-3333-4333-8333-333333333333',
      cacheVersion:
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      bytes: <int>[4, 5, 6],
    );
    cache.markAuthorityValidated(ownerUserId: _owner, mediaId: _media);

    final api = _DeleteQueryProjectionFailureApi();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MemoryQueryPage(api: api, mediaCache: cache),
        ),
      ),
    );
    await tester.enterText(find.byType(TextField).first, '找照片');
    await tester.tap(find.text('从我的记录里找'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('删除最相关记忆'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('确认删除'));
    await tester.pumpAndSettle();

    expect(api.deleteCalls, 1);
    expect(await first.exists(), isFalse);
    expect(await second.exists(), isFalse);
    expect(
      await cache.lookup(ownerUserId: _owner, mediaId: _media),
      isNull,
    );
  });

}
