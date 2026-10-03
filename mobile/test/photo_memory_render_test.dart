import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';
import 'package:jiyidashi/memory_detail_page.dart';

const ownerA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const ownerB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const memoryId = '11111111-1111-4111-8111-111111111111';
const mediaId = '22222222-2222-4222-8222-222222222222';
const sessionId = '33333333-3333-4333-8333-333333333333';

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
  _PhotoApi({
    this.downloadCompleter,
    List<MediaDownloadSession>? downloadSequence,
  })  : downloadSequence = downloadSequence ?? <MediaDownloadSession>[],
        super(baseUrl: 'https://example.invalid/v1') {
    accessToken = 'photo-access';
    authenticatedUserId = ownerA;
  }

  final Completer<MediaDownloadSession>? downloadCompleter;
  final List<MediaDownloadSession> downloadSequence;
  int downloadCalls = 0;

  @override
  Future<Map<String, dynamic>> getMemory(String requestedMemoryId) async {
    expect(requestedMemoryId, memoryId);
    return _photoMemory();
  }

  @override
  Future<MediaDownloadSession> createMediaDownload(String requestedMediaId) async {
    expect(requestedMediaId, mediaId);
    downloadCalls += 1;
    final pending = downloadCompleter;
    if (pending != null) return pending.future;
    if (downloadSequence.isNotEmpty) {
      return downloadSequence.removeAt(0);
    }
    return MediaDownloadSession(
      mediaId: mediaId,
      download: SignedDownloadTarget(
        method: 'GET',
        url: Uri.parse('https://storage.invalid/private-photo.jpg?signature=short-lived'),
        headers: const <String, String>{'x-signed-read': '1'},
        expiresAt: DateTime.utc(2030, 10, 3, 12),
      ),
    );
  }
}

void main() {
  test('media download endpoint returns a validated short-lived GET capability', () async {
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
    expect(signed.download.method, 'GET');
    expect(signed.download.url.host, 'storage.example');
    expect(signed.download.headers['x-object-signature'], 'signed');
    expect(signed.download.expiresAt, DateTime.utc(2030, 10, 3, 12, 5));
    expect(call, 2);
  });

  testWidgets('PHOTO detail asks shared Flutter layer for original media capability',
      (tester) async {
    final api = _PhotoApi();

    await tester.pumpWidget(
      MaterialApp(
        home: MemoryDetailPage(api: api, memoryId: memoryId),
      ),
    );
    await tester.pump();
    await tester.pump();

    expect(api.downloadCalls, greaterThanOrEqualTo(1));
    expect(find.text('测试照片'), findsWidgets);
    expect(find.text('照片'), findsWidgets);
    expect(find.byType(Image), findsOneWidget);

    // Dispose before the test binding's disabled network client can drive further retries.
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('expired photo capability is re-signed instead of reused', (tester) async {
    final api = _PhotoApi(
      downloadSequence: <MediaDownloadSession>[
        MediaDownloadSession(
          mediaId: mediaId,
          download: SignedDownloadTarget(
            method: 'GET',
            url: Uri.parse('https://storage.invalid/expired-photo.jpg?sig=old'),
            headers: const <String, String>{},
            expiresAt: DateTime.utc(2025, 1, 1),
          ),
        ),
        MediaDownloadSession(
          mediaId: mediaId,
          download: SignedDownloadTarget(
            method: 'GET',
            url: Uri.parse('https://storage.invalid/fresh-photo.jpg?sig=new'),
            headers: const <String, String>{},
            expiresAt: DateTime.utc(2030, 10, 3, 12),
          ),
        ),
      ],
    );

    await tester.pumpWidget(
      MaterialApp(
        home: MemoryDetailPage(api: api, memoryId: memoryId),
      ),
    );
    await tester.pump();
    await tester.pump();
    await tester.pump();

    expect(api.downloadCalls, 2);
    final image = tester.widget<Image>(find.byType(Image));
    final provider = image.image as NetworkImage;
    expect(provider.url, contains('fresh-photo.jpg'));
    expect(provider.url, isNot(contains('expired-photo.jpg')));

    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('late photo capability from old owner is never published', (tester) async {
    final gate = Completer<MediaDownloadSession>();
    final api = _PhotoApi(downloadCompleter: gate);

    await tester.pumpWidget(
      MaterialApp(
        home: MemoryDetailPage(api: api, memoryId: memoryId),
      ),
    );
    await tester.pump();
    expect(api.downloadCalls, 1);

    api.authenticatedUserId = ownerB;
    gate.complete(
      MediaDownloadSession(
        mediaId: mediaId,
        download: SignedDownloadTarget(
          method: 'GET',
          url: Uri.parse('https://storage.invalid/stale-owner-a.jpg'),
          headers: const <String, String>{},
          expiresAt: DateTime.utc(2030, 10, 3, 12),
        ),
      ),
    );
    await tester.pump();
    await tester.pump();

    expect(find.byType(Image), findsNothing);
    expect(find.text('stale-owner-a.jpg'), findsNothing);
  });
}
