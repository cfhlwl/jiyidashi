import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';
import 'package:jiyidashi/media_presentation_cache.dart';
import 'package:jiyidashi/memory_detail_page.dart';

const ownerA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const ownerB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const memoryId = '11111111-1111-4111-8111-111111111111';
const mediaId = '22222222-2222-4222-8222-222222222222';
const sessionId = '33333333-3333-4333-8333-333333333333';
const cacheVersion =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

Map<String, dynamic> _sessionPayload() => <String, dynamic>{
      'access_token': 'access-v1',
      'refresh_token': 'refresh-v1-abcdefghijklmnopqrstuvwxyz',
      'session_id': sessionId,
      'token_type': 'bearer',
      'user_id': ownerA,
      'access_expires_at': '2030-10-03T12:00:00Z',
      'refresh_expires_at': '2030-11-03T12:00:00Z',
      'account_deletion_in_progress': false,
    };

Map<String, dynamic> _photoMemory() => <String, dynamic>{
      'id': memoryId,
      'user_id': ownerA,
      'memory_type': 'PHOTO',
      'title': '测试照片',
      'content': '原图应该显示在这里',
      'occurred_at': '2026-10-03T08:00:00Z',
      'source_type': 'USER_PHOTO',
      'confidence': 1.0,
      'place_id': null,
      'latitude': null,
      'longitude': null,
      'is_confirmed': true,
      'metadata_json': <String, dynamic>{'media_id': mediaId},
      'edit_revision': 0,
      'edited_at': null,
      'created_at': '2026-10-03T08:00:00Z',
    };

class _PhotoApi extends JiYiApiClient {
  _PhotoApi() : super(baseUrl: 'https://example.invalid/v1') {
    accessToken = 'photo-access';
    authenticatedUserId = ownerA;
  }

  int capabilityCalls = 0;
  int byteDownloadCalls = 0;

  @override
  Future<Map<String, dynamic>> getMemory(String requestedMemoryId) async {
    expect(requestedMemoryId, memoryId);
    return _photoMemory();
  }

  @override
  Future<MediaDownloadSession> createMediaDownload(String requestedMediaId) async {
    expect(requestedMediaId, mediaId);
    capabilityCalls += 1;
    return MediaDownloadSession(
      mediaId: mediaId,
      cacheVersion: cacheVersion,
      download: SignedDownloadTarget(
        method: 'GET',
        url: Uri.parse('https://storage.invalid/private-photo.jpg?signature=short-lived'),
        headers: const <String, String>{'x-signed-read': '1'},
        expiresAt: DateTime.utc(2030, 10, 3, 12),
      ),
    );
  }

  @override
  Future<Uint8List> downloadSignedMedia(
    SignedDownloadTarget target, {
    int maxBytes = 50 * 1024 * 1024,
  }) async {
    byteDownloadCalls += 1;
    return _validPngBytes();
  }
}

Future<Directory> _tempRoot() =>
    Directory.systemTemp.createTemp('jiyi-photo-detail-');

Uint8List _validPngBytes() => base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
    );

Future<void> _pumpUntil(
  WidgetTester tester,
  bool Function() done, {
  int attempts = 30,
}) async {
  for (var index = 0; index < attempts; index++) {
    await tester.pump(const Duration(milliseconds: 50));
    if (done()) return;
  }
  fail('bounded widget pump did not reach expected state');
}

void main() {
  test('media download endpoint returns stable cache identity plus short-lived GET', () async {
    final store = MemoryAuthSessionStore()..installationId = 'photo-download-install';
    var call = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: store,
      httpClient: MockClient((request) async {
        call += 1;
        if (call == 1) {
          expect(request.url.path, '/v1/auth/login');
          return http.Response(
            jsonEncode(_sessionPayload()),
            200,
            headers: const {'content-type': 'application/json'},
          );
        }
        expect(call, 2);
        expect(request.url.path, '/v1/media/$mediaId/download');
        expect(request.method, 'POST');
        expect(request.headers['authorization'], 'Bearer access-v1');
        return http.Response(
          jsonEncode(<String, dynamic>{
            'media_id': mediaId,
            'cache_version': cacheVersion,
            'download': <String, dynamic>{
              'method': 'GET',
              'url': 'https://storage.example/private.jpg?sig=temporary',
              'headers': <String, String>{'x-object-signature': 'signed'},
              'expires_at': '2030-10-03T12:05:00Z',
            },
          }),
          200,
          headers: const {'content-type': 'application/json'},
        );
      }),
    );

    await api.login(email: 'photo@example.test', password: 'password-123456');
    final signed = await api.createMediaDownload(mediaId);

    expect(signed.mediaId, mediaId);
    expect(signed.cacheVersion, cacheVersion);
    expect(signed.download.method, 'GET');
    expect(signed.download.url.host, 'storage.example');
    expect(signed.download.headers['x-object-signature'], 'signed');
    expect(signed.download.expiresAt, DateTime.utc(2030, 10, 3, 12, 5));
    expect(call, 2);
  });

  testWidgets('PHOTO detail downloads once then renders local cached file',
      (tester) async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));
    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    final api = _PhotoApi();

    await tester.pumpWidget(
      MaterialApp(
        home: MemoryDetailPage(
          api: api,
          memoryId: memoryId,
          mediaCache: cache,
        ),
      ),
    );
    await _pumpUntil(
      tester,
      () => api.capabilityCalls == 1 &&
          api.byteDownloadCalls == 1 &&
          find.byType(Image).evaluate().isNotEmpty,
    );

    expect(api.capabilityCalls, 1);
    expect(api.byteDownloadCalls, 1);
    expect(find.text('测试照片'), findsWidgets);
    expect(find.text('照片'), findsWidgets);
    final image = tester.widget<Image>(find.byType(Image));
    expect(image.image, isA<FileImage>());
    expect(
      await cache.lookup(ownerUserId: ownerA, mediaId: mediaId),
      isNotNull,
    );
  });

  testWidgets('PHOTO detail cache hit does not ask for a signed capability',
      (tester) async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));
    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    await cache.putBytes(
      ownerUserId: ownerA,
      mediaId: mediaId,
      cacheVersion: cacheVersion,
      bytes: _validPngBytes(),
    );
    final api = _PhotoApi();

    await tester.pumpWidget(
      MaterialApp(
        home: MemoryDetailPage(
          api: api,
          memoryId: memoryId,
          mediaCache: cache,
        ),
      ),
    );
    await _pumpUntil(
      tester,
      () => find.byType(Image).evaluate().isNotEmpty,
    );

    expect(api.capabilityCalls, 0);
    expect(api.byteDownloadCalls, 0);
    expect(tester.widget<Image>(find.byType(Image)).image, isA<FileImage>());
  });

  testWidgets('account switch prevents owner A cached image publication',
      (tester) async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));
    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    await cache.putBytes(
      ownerUserId: ownerA,
      mediaId: mediaId,
      cacheVersion: cacheVersion,
      bytes: <int>[0x89, 0x50, 0x4e, 0x47],
    );
    final api = _PhotoApi()..authenticatedUserId = ownerB;

    await tester.pumpWidget(
      MaterialApp(
        home: MemoryDetailPage(
          api: api,
          memoryId: memoryId,
          mediaCache: cache,
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.byType(Image), findsNothing);
    expect(api.capabilityCalls, 0);
    expect(api.byteDownloadCalls, 0);
  });
}
