import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/amap_privacy_consent.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/media_presentation_cache.dart';
import 'package:jiyidashi/v2/family_models.dart';
import 'package:jiyidashi/v2/family_page.dart';

const _viewer = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const _member = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const _family = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const _media = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const _cacheVersion =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

class _Consent implements AmapPrivacyConsentAuthority {
  bool accepted = false;

  @override
  Future<void> accept() async => accepted = true;

  @override
  Future<bool> readAccepted() async => accepted;

  @override
  Future<void> revoke() async => accepted = false;
}

class _FamilySharedApi extends JiYiApiClient {
  _FamilySharedApi() : super(baseUrl: 'https://family-shared.invalid/v1') {
    accessToken = 'token';
    authenticatedUserId = _viewer;
  }

  int photoListCalls = 0;
  int photoSignCalls = 0;
  int byteDownloadCalls = 0;
  bool photosDenied = false;

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    if (method == 'GET' && path == '/family') {
      return <String, dynamic>{
        'family_id': _family,
        'current_user_role': 'OWNER',
        'members': <Map<String, dynamic>>[
          <String, dynamic>{
            'user_id': _viewer,
            'role': 'OWNER',
            'created_at': '2026-10-01T00:00:00Z',
          },
          <String, dynamic>{
            'user_id': _member,
            'role': 'MEMBER',
            'created_at': '2026-10-01T00:00:00Z',
          },
        ],
      };
    }
    if (method == 'GET' && path == '/family/permissions') {
      return <Map<String, dynamic>>[
        <String, dynamic>{
          'grantee_user_id': _member,
          'permissions': <String>[],
        },
      ];
    }
    if (method == 'GET' && path == '/family/members/$_member/photos') {
      photoListCalls += 1;
      if (photosDenied) {
        throw ApiException(403, 'FAMILY_READ_NOT_AUTHORIZED');
      }
      return <Map<String, dynamic>>[
        <String, dynamic>{
          'media_id': _media,
          'content_type': 'image/jpeg',
          'size_bytes': 3,
          'created_at': '2026-10-04T09:00:00Z',
          'completed_at': '2026-10-04T09:00:01Z',
          'cache_version': _cacheVersion,
        },
      ];
    }
    if (method == 'POST' &&
        path == '/family/members/$_member/photos/$_media/download') {
      photoSignCalls += 1;
      return <String, dynamic>{
        'media_id': _media,
        'download': <String, dynamic>{
          'method': 'GET',
          'url': 'https://storage.invalid/family-photo?sig=short',
          'headers': <String, String>{'x-family': '1'},
          'expires_at': '2030-10-04T09:05:00Z',
        },
      };
    }
    if (method == 'GET' &&
        path == '/family/members/$_member/current-location') {
      return <String, dynamic>{
        'resource_owner_user_id': _member,
        'latitude': 31.2304,
        'longitude': 121.4737,
        'accuracy': 8.0,
        'recorded_at': '2026-10-04T10:00:00Z',
        'fresh_until': '2030-10-04T10:15:00Z',
      };
    }
    throw StateError('unexpected family request: $method $path');
  }

  @override
  Future<Uint8List> downloadSignedMedia(
    SignedDownloadTarget target, {
    int maxBytes = 50 * 1024 * 1024,
  }) async {
    byteDownloadCalls += 1;
    return Uint8List.fromList(<int>[1, 2, 3]);
  }
}

Future<void> _pumpUntil(
  WidgetTester tester,
  bool Function() condition, {
  String label = 'condition',
  int maxFrames = 120,
}) async {
  for (var frame = 0; frame < maxFrames; frame++) {
    if (condition()) return;
    await tester.pump(const Duration(milliseconds: 25));
  }
  fail('family widget test did not reach $label');
}

void main() {
  testWidgets(
      'Family shared photos are local-first and revoked authority purges cached bytes',
      (tester) async {
    final root = await Directory.systemTemp.createTemp('jiyi-family-cache-');
    addTearDown(() => root.delete(recursive: true));
    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    final api = _FamilySharedApi();
    final consent = _Consent();

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: FamilyPage(
            api: api,
            mediaCache: cache,
            amapPrivacyConsent: consent,
            photoRenderer: (file) => Text('family-local-photo:${file.path}'),
          ),
        ),
      ),
    );
    await _pumpUntil(
      tester,
      () => find.byKey(const ValueKey('family-shared-open-$_member')).evaluate().isNotEmpty,
      label: 'family member open control',
    );

    await tester.tap(
      find.byKey(const ValueKey('family-shared-open-$_member')),
    );
    await _pumpUntil(
      tester,
      () => find.byKey(const ValueKey('family-read-photos')).evaluate().isNotEmpty,
      label: 'family photo read control',
    );

    await tester.tap(find.byKey(const ValueKey('family-read-photos')));
    await _pumpUntil(
      tester,
      () => find.textContaining('family-local-photo:').evaluate().isNotEmpty,
      label: 'family local photo',
    );

    expect(find.byKey(const ValueKey('family-photo-grid')), findsOneWidget);
    expect(find.textContaining('family-local-photo:'), findsOneWidget);
    expect(api.photoListCalls, 1);
    expect(api.photoSignCalls, 1);
    expect(api.byteDownloadCalls, 1);

    final mediaKey = familyMediaCacheKey(_member, _media);
    final cached = await cache.lookup(
      ownerUserId: _viewer,
      mediaId: mediaKey,
      cacheVersion: _cacheVersion,
    );
    expect(cached, isNotNull);

    // A fresh list read revalidates authority. The exact cached bytes are reused.
    await tester.tap(find.byKey(const ValueKey('family-read-photos')));
    await _pumpUntil(
      tester,
      () => api.photoListCalls >= 2,
      label: 'second family photo authority read',
    );
    expect(api.photoListCalls, 2);
    expect(api.photoSignCalls, 1);
    expect(api.byteDownloadCalls, 1);

    api.photosDenied = true;
    await tester.tap(find.byKey(const ValueKey('family-read-photos')));
    await _pumpUntil(
      tester,
      () => find.textContaining('没有把照片分享给你').evaluate().isNotEmpty,
      label: 'revoked family photo message',
    );

    expect(find.textContaining('没有把照片分享给你'), findsOneWidget);
    expect(
      await cache.lookup(ownerUserId: _viewer, mediaId: mediaKey),
      isNull,
    );
    expect(
      cache.hasFreshAuthorityLease(
        ownerUserId: _viewer,
        mediaId: mediaKey,
      ),
      isFalse,
    );
  });

  testWidgets('Family current location asks for AMap disclosure before map use',
      (tester) async {
    final root = await Directory.systemTemp.createTemp('jiyi-family-map-');
    addTearDown(() => root.delete(recursive: true));
    final api = _FamilySharedApi();
    final consent = _Consent();

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: FamilyPage(
            api: api,
            mediaCache: LocalMediaCache(rootDirectoryProvider: () async => root),
            amapPrivacyConsent: consent,
          ),
        ),
      ),
    );
    await _pumpUntil(
      tester,
      () => find.byKey(const ValueKey('family-shared-open-$_member')).evaluate().isNotEmpty,
      label: 'family member open control',
    );
    await tester.tap(
      find.byKey(const ValueKey('family-shared-open-$_member')),
    );
    await _pumpUntil(
      tester,
      () => find.byKey(const ValueKey('family-read-location')).evaluate().isNotEmpty,
      label: 'family location read control',
    );

    await tester.tap(find.byKey(const ValueKey('family-read-location')));
    await _pumpUntil(
      tester,
      () => find.byKey(const ValueKey('family-amap-privacy-accept')).evaluate().isNotEmpty,
      label: 'family map privacy control',
    );
    expect(
      find.byKey(const ValueKey('family-amap-privacy-accept')),
      findsOneWidget,
    );

    await tester.tap(find.byKey(const ValueKey('family-amap-privacy-accept')));
    await _pumpUntil(
      tester,
      () => find.textContaining('高德地图 SDK').evaluate().isNotEmpty,
      label: 'AMap disclosure',
    );
    expect(find.textContaining('高德地图 SDK'), findsOneWidget);
    expect(consent.accepted, isFalse);

    await tester.tap(find.byKey(const ValueKey('amap-privacy-confirm')));
    await _pumpUntil(
      tester,
      () => consent.accepted,
      label: 'AMap consent acceptance',
    );
    expect(consent.accepted, isTrue);
  });
}
