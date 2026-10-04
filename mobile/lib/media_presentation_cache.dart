import 'dart:io';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:sqflite/sqflite.dart';

import 'api_client.dart';

typedef MediaCacheRootProvider = Future<Directory> Function();

class MediaCacheException implements Exception {
  const MediaCacheException(this.message);

  final String message;

  @override
  String toString() => 'MediaCacheException: $message';
}

class MediaUnavailableOffline implements Exception {
  const MediaUnavailableOffline();
}

class LocalMediaCache {
  LocalMediaCache({
    MediaCacheRootProvider? rootDirectoryProvider,
    this.maxBytes = 256 * 1024 * 1024,
    this.authorityLeaseDuration = const Duration(minutes: 5),
    DateTime Function()? nowProvider,
  })  : _rootDirectoryProvider =
            rootDirectoryProvider ?? _defaultRootDirectoryProvider,
        _nowProvider = nowProvider ?? DateTime.now {
    if (maxBytes <= 0) {
      throw ArgumentError.value(maxBytes, 'maxBytes', 'must be positive');
    }
  }

  final MediaCacheRootProvider _rootDirectoryProvider;
  final int maxBytes;
  final Duration authorityLeaseDuration;
  final DateTime Function() _nowProvider;
  final Random _random = Random.secure();
  final Map<String, DateTime> _authorityValidatedAt = <String, DateTime>{};

  static Future<Directory> _defaultRootDirectoryProvider() async {
    final databasePath = await getDatabasesPath();
    return Directory('$databasePath/jiyi_media_cache_v1');
  }

  Future<File?> lookup({
    required String ownerUserId,
    required String mediaId,
    String? cacheVersion,
  }) async {
    final owner = _safeComponent(ownerUserId, 'ownerUserId');
    final media = _safeComponent(mediaId, 'mediaId');
    final directory = await _ownerDirectory(owner, create: false);
    if (!await directory.exists()) return null;

    File? candidate;
    if (cacheVersion != null) {
      final version = _safeVersion(cacheVersion);
      candidate = File('${directory.path}/${_fileName(media, version)}');
    } else {
      final prefix = '${media.toLowerCase()}_';
      final files = <File>[];
      await for (final entity in directory.list(followLinks: false)) {
        if (entity is File) {
          final name = _basename(entity.path);
          if (name.startsWith(prefix) && name.endsWith('.media')) {
            files.add(entity);
          }
        }
      }
      if (files.isEmpty) return null;
      files.sort((left, right) {
        final l = left.statSync().modified;
        final r = right.statSync().modified;
        return r.compareTo(l);
      });
      candidate = files.first;
    }

    if (!await candidate.exists()) return null;
    try {
      final length = await candidate.length();
      if (length <= 0 || length > maxBytes) {
        await _deleteQuietly(candidate);
        return null;
      }
      await candidate.setLastModified(DateTime.now().toUtc());
      return candidate;
    } on FileSystemException {
      await _deleteQuietly(candidate);
      return null;
    }
  }

  Future<File> putBytes({
    required String ownerUserId,
    required String mediaId,
    required String cacheVersion,
    required List<int> bytes,
  }) async {
    if (bytes.isEmpty) {
      throw const MediaCacheException('refuse empty media cache object');
    }
    if (bytes.length > maxBytes) {
      throw const MediaCacheException('media object exceeds cache ceiling');
    }

    final owner = _safeComponent(ownerUserId, 'ownerUserId');
    final media = _safeComponent(mediaId, 'mediaId');
    final version = _safeVersion(cacheVersion);
    final directory = await _ownerDirectory(owner, create: true);
    final target = File('${directory.path}/${_fileName(media, version)}');
    final temporary = File(
      '${target.path}.${DateTime.now().microsecondsSinceEpoch}.'
      '${_random.nextInt(1 << 32)}.part',
    );

    try {
      await temporary.writeAsBytes(bytes, flush: true);
      if (await temporary.length() != bytes.length) {
        throw const MediaCacheException('partial media cache write');
      }
      if (await target.exists()) {
        await target.delete();
      }
      await temporary.rename(target.path);
      await target.setLastModified(DateTime.now().toUtc());
    } catch (_) {
      await _deleteQuietly(temporary);
      rethrow;
    }

    await _cleanupPartials(directory);
    await _evictToLimit(keepPath: target.path);
    return target;
  }

  Future<File> seedFromFile({
    required String ownerUserId,
    required String mediaId,
    required String cacheVersion,
    required File source,
  }) async {
    if (!await source.exists()) {
      throw const MediaCacheException('capture source file is missing');
    }
    final length = await source.length();
    if (length <= 0 || length > maxBytes) {
      throw const MediaCacheException('capture source size is invalid');
    }
    return putBytes(
      ownerUserId: ownerUserId,
      mediaId: mediaId,
      cacheVersion: cacheVersion,
      bytes: await source.readAsBytes(),
    );
  }

  bool hasFreshAuthorityLease({
    required String ownerUserId,
    required String mediaId,
  }) {
    final key = _authorityKey(ownerUserId, mediaId);
    final validatedAt = _authorityValidatedAt[key];
    if (validatedAt == null) return false;
    if (authorityLeaseDuration <= Duration.zero) return false;
    final age = _nowProvider().toUtc().difference(validatedAt);
    return !age.isNegative && age <= authorityLeaseDuration;
  }

  void markAuthorityValidated({
    required String ownerUserId,
    required String mediaId,
  }) {
    _authorityValidatedAt[_authorityKey(ownerUserId, mediaId)] =
        _nowProvider().toUtc();
  }

  void invalidateAuthority({
    required String ownerUserId,
    required String mediaId,
  }) {
    _authorityValidatedAt.remove(_authorityKey(ownerUserId, mediaId));
  }

  Future<void> invalidateMedia({
    required String ownerUserId,
    required String mediaId,
  }) async {
    invalidateAuthority(ownerUserId: ownerUserId, mediaId: mediaId);
    final owner = _safeComponent(ownerUserId, 'ownerUserId');
    final media = _safeComponent(mediaId, 'mediaId').toLowerCase();
    final directory = await _ownerDirectory(owner, create: false);
    if (!await directory.exists()) return;
    await for (final entity in directory.list(followLinks: false)) {
      if (entity is File) {
        final name = _basename(entity.path);
        if (name.startsWith('${media}_')) {
          await _deleteQuietly(entity);
        }
      }
    }
  }

  Future<void> purgeOwner(String ownerUserId) async {
    final owner = _safeComponent(ownerUserId, 'ownerUserId');
    final prefix = '${owner.toLowerCase()}::';
    _authorityValidatedAt.removeWhere((key, _) => key.startsWith(prefix));
    final directory = await _ownerDirectory(owner, create: false);
    if (await directory.exists()) {
      await directory.delete(recursive: true);
    }
  }

  Future<Directory> _ownerDirectory(
    String owner, {
    required bool create,
  }) async {
    final root = await _rootDirectoryProvider();
    final directory = Directory('${root.path}/owners/$owner');
    if (create && !await directory.exists()) {
      await directory.create(recursive: true);
    }
    return directory;
  }

  Future<void> _evictToLimit({required String keepPath}) async {
    final root = await _rootDirectoryProvider();
    if (!await root.exists()) return;

    final entries = <({File file, int size, DateTime modified})>[];
    var total = 0;
    await for (final entity
        in root.list(recursive: true, followLinks: false)) {
      if (entity is! File || !entity.path.endsWith('.media')) continue;
      try {
        final stat = await entity.stat();
        total += stat.size;
        entries.add((file: entity, size: stat.size, modified: stat.modified));
      } on FileSystemException {
        await _deleteQuietly(entity);
      }
    }
    if (total <= maxBytes) return;

    entries.sort((left, right) => left.modified.compareTo(right.modified));
    for (final entry in entries) {
      if (total <= maxBytes) break;
      if (entry.file.path == keepPath) continue;
      await _deleteQuietly(entry.file);
      total -= entry.size;
    }
    if (total > maxBytes) {
      throw const MediaCacheException('cache ceiling cannot retain media object');
    }
  }

  Future<void> _cleanupPartials(Directory directory) async {
    if (!await directory.exists()) return;
    await for (final entity in directory.list(followLinks: false)) {
      if (entity is File && entity.path.endsWith('.part')) {
        await _deleteQuietly(entity);
      }
    }
  }

  Future<void> _deleteQuietly(File file) async {
    try {
      if (await file.exists()) await file.delete();
    } on FileSystemException {
      // Cache cleanup is best effort; canonical media remains server-owned.
    }
  }
}

class LocalMediaThumbnail extends StatefulWidget {
  const LocalMediaThumbnail({
    super.key,
    required this.api,
    required this.mediaId,
    this.cache,
    this.width = 88,
    this.height = 88,
    this.borderRadius = 14,
  });

  final JiYiApiClient api;
  final String mediaId;
  final LocalMediaCache? cache;
  final double width;
  final double height;
  final double borderRadius;

  @override
  State<LocalMediaThumbnail> createState() => _LocalMediaThumbnailState();
}

class _LocalMediaThumbnailState extends State<LocalMediaThumbnail> {
  late final LocalMediaCache _cache = widget.cache ?? LocalMediaCache();
  File? _file;
  bool _unavailable = false;
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    _resolve();
  }

  @override
  void didUpdateWidget(covariant LocalMediaThumbnail oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.mediaId != widget.mediaId ||
        oldWidget.api != widget.api) {
      _resolve();
    }
  }

  Future<void> _resolve() async {
    final generation = ++_generation;
    final owner = widget.api.authenticatedUserId;
    if (owner == null || owner.trim().isEmpty) {
      if (mounted && generation == _generation) {
        setState(() {
          _file = null;
          _unavailable = true;
        });
      }
      return;
    }
    try {
      final file = await MediaPresentationResolver(
        api: widget.api,
        cache: _cache,
      ).resolve(
        ownerUserId: owner,
        mediaId: widget.mediaId,
      );
      if (!mounted || generation != _generation) return;
      setState(() {
        _file = file;
        _unavailable = false;
      });
    } catch (_) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _file = null;
        _unavailable = true;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final file = _file;
    return ClipRRect(
      borderRadius: BorderRadius.circular(widget.borderRadius),
      child: SizedBox(
        width: widget.width,
        height: widget.height,
        child: file == null
            ? ColoredBox(
                color: Theme.of(context).colorScheme.surfaceContainerLow,
                child: Icon(
                  _unavailable
                      ? Icons.image_not_supported_outlined
                      : Icons.photo_outlined,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              )
            : Image.file(
                file,
                fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => ColoredBox(
                  color: Theme.of(context).colorScheme.surfaceContainerLow,
                  child: const Icon(Icons.broken_image_outlined),
                ),
              ),
      ),
    );
  }
}

class MediaPresentationResolver {
  const MediaPresentationResolver({
    required this.api,
    required this.cache,
    this.maxDownloadBytes = 50 * 1024 * 1024,
  });

  final JiYiApiClient api;
  final LocalMediaCache cache;
  final int maxDownloadBytes;

  Future<File> resolve({
    required String ownerUserId,
    required String mediaId,
    bool offline = false,
  }) async {
    final currentOwner = api.authenticatedUserId;
    if (currentOwner == null ||
        currentOwner.toLowerCase() != ownerUserId.toLowerCase()) {
      throw const MediaCacheException('media cache owner is not current session');
    }
    final sessionVersion = api.sessionVersion;

    final cached = await cache.lookup(
      ownerUserId: ownerUserId,
      mediaId: mediaId,
    );
    if (offline) {
      if (cached != null) return cached;
      throw const MediaUnavailableOffline();
    }
    if (cached != null &&
        cache.hasFreshAuthorityLease(
          ownerUserId: ownerUserId,
          mediaId: mediaId,
        )) {
      return cached;
    }

    late final MediaDownloadSession capability;
    try {
      capability = await api.createMediaDownload(mediaId);
    } on ApiException catch (error) {
      if (error.statusCode == 403 || error.statusCode == 404) {
        await cache.invalidateMedia(
          ownerUserId: ownerUserId,
          mediaId: mediaId,
        );
      }
      rethrow;
    }
    _assertCurrent(ownerUserId, sessionVersion);

    final exactCached = await cache.lookup(
      ownerUserId: ownerUserId,
      mediaId: mediaId,
      cacheVersion: capability.cacheVersion,
    );
    cache.markAuthorityValidated(
      ownerUserId: ownerUserId,
      mediaId: mediaId,
    );
    if (exactCached != null) return exactCached;

    final bytes = await api.downloadSignedMedia(
      capability.download,
      maxBytes: maxDownloadBytes,
    );
    _assertCurrent(ownerUserId, sessionVersion);

    final stored = await cache.putBytes(
      ownerUserId: ownerUserId,
      mediaId: capability.mediaId,
      cacheVersion: capability.cacheVersion,
      bytes: bytes,
    );
    cache.markAuthorityValidated(
      ownerUserId: ownerUserId,
      mediaId: capability.mediaId,
    );
    return stored;
  }

  void _assertCurrent(String ownerUserId, int sessionVersion) {
    if (api.sessionVersion != sessionVersion ||
        api.authenticatedUserId?.toLowerCase() != ownerUserId.toLowerCase()) {
      throw const MediaCacheException(
        'session changed while resolving media cache',
      );
    }
  }
}

String _authorityKey(String ownerUserId, String mediaId) {
  final owner = _safeComponent(ownerUserId, 'ownerUserId').toLowerCase();
  final media = _safeComponent(mediaId, 'mediaId').toLowerCase();
  return '$owner::$media';
}

String _safeComponent(String value, String name) {
  final normalized = value.trim();
  if (!RegExp(r'^[A-Za-z0-9_-]{1,128}$').hasMatch(normalized)) {
    throw ArgumentError.value(value, name, 'unsafe cache identity');
  }
  return normalized;
}

String _safeVersion(String value) {
  final normalized = value.trim().toLowerCase();
  if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(normalized)) {
    throw ArgumentError.value(value, 'cacheVersion', 'invalid cache version');
  }
  return normalized;
}

String _fileName(String mediaId, String version) =>
    '${mediaId.toLowerCase()}_$version.media';

String _basename(String path) {
  final normalized = path.replaceAll('\\', '/');
  return normalized.substring(normalized.lastIndexOf('/') + 1);
}
