import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/media_presentation_cache.dart';
import 'package:jiyidashi/stage1_app.dart';

const _owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const _memory = '11111111-1111-4111-8111-111111111111';
const _media = '22222222-2222-4222-8222-222222222222';
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

class _TrackingMediaCache extends LocalMediaCache {
  _TrackingMediaCache()
      : super(rootDirectoryProvider: () async => Directory.systemTemp);

  final List<String> invalidatedMedia = <String>[];
  final List<String> purgedOwners = <String>[];

  @override
  Future<void> invalidateMedia({
    required String ownerUserId,
    required String mediaId,
  }) async {
    invalidateAuthority(ownerUserId: ownerUserId, mediaId: mediaId);
    invalidatedMedia.add('$ownerUserId::$mediaId');
  }

  @override
  Future<void> purgeOwner(String ownerUserId) async {
    // The concrete LocalMediaCache purge semantics, including real file
    // deletion, are covered in media_presentation_cache_test.dart. This spy
    // keeps the widget integration test focused on selecting the correct
    // authoritative invalidation boundary without mixing Flutter fake async
    // with host filesystem I/O.
    invalidateAuthority(ownerUserId: ownerUserId, mediaId: _media);
    purgedOwners.add(ownerUserId);
  }
}

Future<void> _pumpUntil(
  WidgetTester tester,
  bool Function() condition, {
  required String reason,
}) async {
  for (var attempt = 0; attempt < 40; attempt++) {
    await tester.pump(const Duration(milliseconds: 25));
    if (condition()) return;
  }
  fail('Timed out waiting for $reason');
}

void main() {
  testWidgets('Memory Query delete invalidates the deleted photo cache',
      (tester) async {
    final cache = _TrackingMediaCache();
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
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await _pumpUntil(
      tester,
      () => find.text('删除最相关记忆').evaluate().isNotEmpty,
      reason: 'query result actions',
    );

    final deleteAction = find.text('删除最相关记忆');
    await tester.ensureVisible(deleteAction);
    await tester.pump();
    await tester.tap(deleteAction);
    await _pumpUntil(
      tester,
      () => find.text('删除这条记忆？').evaluate().isNotEmpty,
      reason: 'delete confirmation dialog',
    );
    expect(find.text('删除这条记忆？'), findsOneWidget);

    await tester.tap(find.text('确认删除'));
    await _pumpUntil(
      tester,
      () => api.deleteCalls == 1 && cache.invalidatedMedia.isNotEmpty,
      reason: 'targeted media invalidation',
    );

    expect(api.deleteCalls, 1);
    expect(cache.invalidatedMedia, <String>['$_owner::$_media']);
    expect(cache.purgedOwners, isEmpty);
    expect(
      cache.hasFreshAuthorityLease(ownerUserId: _owner, mediaId: _media),
      isFalse,
    );
  });

  testWidgets(
      'Memory Query delete purges owner cache when deleted media projection is unavailable',
      (tester) async {
    final cache = _TrackingMediaCache();
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
    await tester.tap(find.byKey(const ValueKey('memory-query-submit')));
    await _pumpUntil(
      tester,
      () => find.text('删除最相关记忆').evaluate().isNotEmpty,
      reason: 'query result actions',
    );

    final deleteAction = find.text('删除最相关记忆');
    await tester.ensureVisible(deleteAction);
    await tester.pump();
    await tester.tap(deleteAction);
    await _pumpUntil(
      tester,
      () => find.text('删除这条记忆？').evaluate().isNotEmpty,
      reason: 'delete confirmation dialog',
    );
    await tester.tap(find.text('确认删除'));
    await _pumpUntil(
      tester,
      () => api.deleteCalls == 1 && cache.purgedOwners.isNotEmpty,
      reason: 'owner cache purge fallback',
    );

    expect(api.deleteCalls, 1);
    expect(cache.invalidatedMedia, isEmpty);
    expect(cache.purgedOwners, <String>[_owner]);
    expect(
      cache.hasFreshAuthorityLease(ownerUserId: _owner, mediaId: _media),
      isFalse,
    );
  });

}
