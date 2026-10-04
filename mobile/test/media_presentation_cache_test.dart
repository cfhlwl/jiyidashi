import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/media_presentation_cache.dart';

const _ownerA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const _ownerB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const _mediaA = '11111111-1111-4111-8111-111111111111';
const _mediaB = '22222222-2222-4222-8222-222222222222';
const _versionA =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _versionB =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

class _MediaApi extends JiYiApiClient {
  _MediaApi({required String owner})
      : super(baseUrl: 'https://media.invalid/v1') {
    accessToken = 'token';
    authenticatedUserId = owner;
  }

  int capabilityCalls = 0;
  int downloadCalls = 0;
  String cacheVersion = _versionA;
  Uint8List bytes = Uint8List.fromList(<int>[1, 2, 3, 4]);
  Object? capabilityError;

  @override
  Future<MediaDownloadSession> createMediaDownload(String mediaId) async {
    capabilityCalls += 1;
    final error = capabilityError;
    if (error != null) throw error;
    return MediaDownloadSession(
      mediaId: mediaId,
      cacheVersion: cacheVersion,
      download: SignedDownloadTarget(
        method: 'GET',
        url: Uri.parse('https://storage.invalid/object'),
        headers: const <String, String>{},
        expiresAt: DateTime.now().toUtc().add(const Duration(minutes: 5)),
      ),
    );
  }

  @override
  Future<Uint8List> downloadSignedMedia(
    SignedDownloadTarget target, {
    int maxBytes = 50 * 1024 * 1024,
  }) async {
    downloadCalls += 1;
    if (bytes.length > maxBytes) {
      throw ProtocolException('too large');
    }
    return bytes;
  }
}

Future<Directory> _tempRoot() => Directory.systemTemp.createTemp('jiyi-media-cache-');

void main() {
  test('cache is owner scoped and account B cannot resolve owner A bytes', () async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));

    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    await cache.putBytes(
      ownerUserId: _ownerA,
      mediaId: _mediaA,
      cacheVersion: _versionA,
      bytes: <int>[1, 2, 3],
    );

    expect(
      await cache.lookup(ownerUserId: _ownerA, mediaId: _mediaA),
      isNotNull,
    );
    expect(
      await cache.lookup(ownerUserId: _ownerB, mediaId: _mediaA),
      isNull,
    );

    final api = _MediaApi(owner: _ownerB);
    final resolver = MediaPresentationResolver(api: api, cache: cache);
    expect(
      () => resolver.resolve(ownerUserId: _ownerA, mediaId: _mediaA),
      throwsA(isA<MediaCacheException>()),
    );
    expect(api.capabilityCalls, 0);
    expect(api.downloadCalls, 0);
  });

  test('cache hit avoids download capability and works offline', () async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));

    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    await cache.putBytes(
      ownerUserId: _ownerA,
      mediaId: _mediaA,
      cacheVersion: _versionA,
      bytes: <int>[7, 8, 9],
    );
    final api = _MediaApi(owner: _ownerA);
    final resolver = MediaPresentationResolver(api: api, cache: cache);

    final file = await resolver.resolve(
      ownerUserId: _ownerA,
      mediaId: _mediaA,
      offline: true,
    );

    expect(await file.readAsBytes(), <int>[7, 8, 9]);
    expect(api.capabilityCalls, 0);
    expect(api.downloadCalls, 0);
  });

  test('cache miss downloads once then subsequent read is local', () async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));

    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    final api = _MediaApi(owner: _ownerA);
    final resolver = MediaPresentationResolver(api: api, cache: cache);

    final first = await resolver.resolve(ownerUserId: _ownerA, mediaId: _mediaA);
    expect(await first.readAsBytes(), api.bytes);
    expect(api.capabilityCalls, 1);
    expect(api.downloadCalls, 1);

    final second = await resolver.resolve(
      ownerUserId: _ownerA,
      mediaId: _mediaA,
      offline: true,
    );
    expect(await second.readAsBytes(), api.bytes);
    expect(api.capabilityCalls, 1);
    expect(api.downloadCalls, 1);
  });

  test('online cached media revalidates authority without redownload', () async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));

    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    final seeded = await cache.putBytes(
      ownerUserId: _ownerA,
      mediaId: _mediaA,
      cacheVersion: _versionA,
      bytes: <int>[7, 8, 9],
    );
    final api = _MediaApi(owner: _ownerA);
    final resolver = MediaPresentationResolver(api: api, cache: cache);

    final resolved =
        await resolver.resolve(ownerUserId: _ownerA, mediaId: _mediaA);

    expect(resolved.path, seeded.path);
    expect(api.capabilityCalls, 1);
    expect(api.downloadCalls, 0);

    final second =
        await resolver.resolve(ownerUserId: _ownerA, mediaId: _mediaA);
    expect(second.path, seeded.path);
    expect(api.capabilityCalls, 1);
    expect(api.downloadCalls, 0);
  });

  test('expired media authority lease revalidates without redownload', () async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));
    var now = DateTime.utc(2026, 10, 4, 12);

    final cache = LocalMediaCache(
      rootDirectoryProvider: () async => root,
      authorityLeaseDuration: const Duration(minutes: 5),
      nowProvider: () => now,
    );
    await cache.putBytes(
      ownerUserId: _ownerA,
      mediaId: _mediaA,
      cacheVersion: _versionA,
      bytes: <int>[7, 8, 9],
    );
    cache.markAuthorityValidated(ownerUserId: _ownerA, mediaId: _mediaA);

    final api = _MediaApi(owner: _ownerA);
    final resolver = MediaPresentationResolver(api: api, cache: cache);

    await resolver.resolve(ownerUserId: _ownerA, mediaId: _mediaA);
    expect(api.capabilityCalls, 0);

    now = now.add(const Duration(minutes: 6));
    await resolver.resolve(ownerUserId: _ownerA, mediaId: _mediaA);

    expect(api.capabilityCalls, 1);
    expect(api.downloadCalls, 0);
  });

  test('server revocation removes stale cached media immediately', () async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));

    final cache = LocalMediaCache(
      rootDirectoryProvider: () async => root,
      authorityLeaseDuration: Duration.zero,
    );
    final seeded = await cache.putBytes(
      ownerUserId: _ownerA,
      mediaId: _mediaA,
      cacheVersion: _versionA,
      bytes: <int>[7, 8, 9],
    );
    final api = _MediaApi(owner: _ownerA)
      ..capabilityError = ApiException(403, 'MEDIA_ACCESS_REVOKED');
    final resolver = MediaPresentationResolver(api: api, cache: cache);

    await expectLater(
      resolver.resolve(ownerUserId: _ownerA, mediaId: _mediaA),
      throwsA(isA<ApiException>()),
    );

    expect(api.capabilityCalls, 1);
    expect(api.downloadCalls, 0);
    expect(await seeded.exists(), isFalse);
    expect(
      await cache.lookup(ownerUserId: _ownerA, mediaId: _mediaA),
      isNull,
    );
  });

  test('uncached offline media fails bounded without network request', () async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));

    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    final api = _MediaApi(owner: _ownerA);
    final resolver = MediaPresentationResolver(api: api, cache: cache);

    expect(
      () => resolver.resolve(
        ownerUserId: _ownerA,
        mediaId: _mediaA,
        offline: true,
      ),
      throwsA(isA<MediaUnavailableOffline>()),
    );
    expect(api.capabilityCalls, 0);
    expect(api.downloadCalls, 0);
  });

  test('corrupt zero-byte cache entry is removed and treated as miss', () async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));

    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    final file = await cache.putBytes(
      ownerUserId: _ownerA,
      mediaId: _mediaA,
      cacheVersion: _versionA,
      bytes: <int>[1, 2, 3],
    );
    await file.writeAsBytes(const <int>[], flush: true);

    expect(
      await cache.lookup(
        ownerUserId: _ownerA,
        mediaId: _mediaA,
        cacheVersion: _versionA,
      ),
      isNull,
    );
    expect(await file.exists(), isFalse);
  });

  test('bounded eviction removes least recently used media only', () async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));

    final cache = LocalMediaCache(
      rootDirectoryProvider: () async => root,
      maxBytes: 5,
    );
    final first = await cache.putBytes(
      ownerUserId: _ownerA,
      mediaId: _mediaA,
      cacheVersion: _versionA,
      bytes: <int>[1, 2, 3],
    );
    await Future<void>.delayed(const Duration(milliseconds: 20));
    final second = await cache.putBytes(
      ownerUserId: _ownerA,
      mediaId: _mediaB,
      cacheVersion: _versionB,
      bytes: <int>[4, 5, 6],
    );

    expect(await first.exists(), isFalse);
    expect(await second.exists(), isTrue);
  });

  test('purgeOwner removes only that owner cache', () async {
    final root = await _tempRoot();
    addTearDown(() => root.delete(recursive: true));

    final cache = LocalMediaCache(rootDirectoryProvider: () async => root);
    await cache.putBytes(
      ownerUserId: _ownerA,
      mediaId: _mediaA,
      cacheVersion: _versionA,
      bytes: <int>[1],
    );
    await cache.putBytes(
      ownerUserId: _ownerB,
      mediaId: _mediaA,
      cacheVersion: _versionA,
      bytes: <int>[2],
    );

    await cache.purgeOwner(_ownerA);

    expect(
      await cache.lookup(ownerUserId: _ownerA, mediaId: _mediaA),
      isNull,
    );
    expect(
      await cache.lookup(ownerUserId: _ownerB, mediaId: _mediaA),
      isNotNull,
    );
  });


}
