import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:exif/exif.dart';
import 'package:image_picker/image_picker.dart';

import 'capture_media.dart' show detectImageContentTypeFromPrefix;

/// Metadata extracted from the selected source file, never from import time,
/// EXIF DateTime (file modified time) or a guessed device time zone.
///
/// A capture wall-clock without OffsetTimeOriginal is useful for display, but
/// is *not* an absolute occurred_at timestamp. No Visit or location sample may
/// be inferred from a photo's GPS tags.
class PhotoCaptureEvidence {
  const PhotoCaptureEvidence({
    this.localCaptureTime,
    this.captureTimeUtc,
    this.utcOffsetMinutes,
    this.latitude,
    this.longitude,
    this.orientation,
    this.metadataUnreadable = false,
  });

  final String? localCaptureTime;
  final DateTime? captureTimeUtc;
  final int? utcOffsetMinutes;
  final double? latitude;
  final double? longitude;
  final int? orientation;
  final bool metadataUnreadable;

  bool get hasVerifiedCaptureInstant => captureTimeUtc != null;
  bool get hasGps => latitude != null && longitude != null;

  static const unknown = PhotoCaptureEvidence();

  static PhotoCaptureEvidence fromExifTags(Map<String, IfdTag> tags) {
    final wallTime = _parseWallTime(tags['EXIF DateTimeOriginal']?.printable);
    final offset = _parseOffset(tags['EXIF OffsetTimeOriginal']?.printable);
    final captureTimeUtc = wallTime == null || offset == null
        ? null
        : wallTime.$2.subtract(Duration(minutes: offset));
    final latitude = _gpsDegrees(
      tags['GPS GPSLatitude'],
      tags['GPS GPSLatitudeRef']?.printable,
      positiveDirection: 'N',
      negativeDirection: 'S',
      maximum: 90,
    );
    final longitude = _gpsDegrees(
      tags['GPS GPSLongitude'],
      tags['GPS GPSLongitudeRef']?.printable,
      positiveDirection: 'E',
      negativeDirection: 'W',
      maximum: 180,
    );

    int? orientation;
    final value = tags['Image Orientation']?.values;
    if (value != null) {
      try {
        final candidate = value.firstAsInt();
        if (candidate >= 1 && candidate <= 8) orientation = candidate;
      } catch (_) {
        // Orientation is optional: corrupted metadata never changes image bytes.
      }
    }

    return PhotoCaptureEvidence(
      localCaptureTime: wallTime?.$1,
      captureTimeUtc: captureTimeUtc,
      utcOffsetMinutes: captureTimeUtc == null ? null : offset,
      latitude: latitude != null && longitude != null ? latitude : null,
      longitude: latitude != null && longitude != null ? longitude : null,
      orientation: orientation,
    );
  }

  static (String, DateTime)? _parseWallTime(String? raw) {
    final input = raw?.trim();
    if (input == null) return null;
    final matched = RegExp(
      r'^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})$',
    ).firstMatch(input);
    if (matched == null) return null;
    final nums = List<int>.generate(
      6, (i) => int.parse(matched.group(i + 1)!),
    );
    if (nums[0] < 1900 || nums[0] > DateTime.now().toUtc().year + 1) return null;
    final value = DateTime.utc(
      nums[0], nums[1], nums[2], nums[3], nums[4], nums[5],
    );
    // Dart normalizes overflow, but EXIF fields must be physically valid.
    if (value.year != nums[0] || value.month != nums[1] ||
        value.day != nums[2] || value.hour != nums[3] ||
        value.minute != nums[4] || value.second != nums[5]) return null;
    return (
      '${nums[0].toString().padLeft(4, '0')}-'
      '${nums[1].toString().padLeft(2, '0')}-'
      '${nums[2].toString().padLeft(2, '0')} '
      '${nums[3].toString().padLeft(2, '0')}:'
      '${nums[4].toString().padLeft(2, '0')}:'
      '${nums[5].toString().padLeft(2, '0')}',
      value,
    );
  }

  static int? _parseOffset(String? raw) {
    final matched = RegExp(r'^([+-])(\d{2}):(\d{2})$')
        .firstMatch(raw?.trim() ?? '');
    if (matched == null) return null;
    final hours = int.parse(matched.group(2)!);
    final minutes = int.parse(matched.group(3)!);
    if (hours > 14 || minutes > 59 || (hours == 14 && minutes != 0)) {
      return null;
    }
    return (hours * 60 + minutes) * (matched.group(1) == '-' ? -1 : 1);
  }

  static double? _gpsDegrees(
    IfdTag? tag,
    String? direction, {
    required String positiveDirection,
    required String negativeDirection,
    required double maximum,
  }) {
    final ref = direction?.trim().toUpperCase();
    if (ref != positiveDirection && ref != negativeDirection) return null;
    final parts = tag?.values.toList();
    if (parts == null || parts.length != 3) return null;
    final values = <double>[];
    for (final part in parts) {
      final numeric = switch (part) {
        Ratio r when r.denominator > 0 => r.toDouble(),
        _ => double.nan,
      };
      if (!numeric.isFinite || numeric < 0) return null;
      values.add(numeric);
    }
    if (values[1] >= 60 || values[2] >= 60) return null;
    final magnitude = values[0] + values[1] / 60 + values[2] / 3600;
    if (magnitude > maximum) return null;
    // Ref and numeric components must both exist; do not construct half a fix.
    return magnitude * (ref == negativeDirection ? -1 : 1);
  }
}

class SelectedPhotoImport {
  const SelectedPhotoImport({
    required this.path,
    required this.originalFilename,
    required this.bytes,
    required this.contentType,
    required this.contentSha256,
    required this.evidence,
  });

  final String path;
  final String originalFilename;
  final int bytes;
  final String contentType;
  final String contentSha256;
  final PhotoCaptureEvidence evidence;
}

class PhotoImportSelection {
  const PhotoImportSelection({
    required this.selected,
    required this.failedNames,
    required this.duplicates,
  });

  final List<SelectedPhotoImport> selected;
  final List<String> failedNames;
  final int duplicates;
}

/// The picker reads *only* assets the user explicitly selects. No app-launch
/// gallery enumeration, no device location permission, no upload, no inference.
class PhotoImportPicker {
  PhotoImportPicker({ImagePicker? picker}) : _picker = picker ?? ImagePicker();
  final ImagePicker _picker;

  static const maxSelected = 20;
  static const maxBytesPerPhoto = 50 * 1024 * 1024;

  Future<PhotoImportSelection> pick() async {
    final picked = await _picker.pickMultiImage(
      limit: maxSelected,
      // On iOS this avoids requesting broad Photo Library permission merely
      // to choose items. If the selection copy lacks source EXIF, keep it unknown.
      requestFullMetadata: false,
    );
    if (picked.length > maxSelected) {
      throw StateError('系统选择器返回数量超过限定值');
    }
    final good = <SelectedPhotoImport>[];
    final failures = <String>[];
    final fingerprints = <String>{};
    var duplicates = 0;
    for (final item in picked) {
      try {
        final file = File(item.path);
        final length = await file.length();
        if (length <= 0 || length > maxBytesPerPhoto) {
          throw const FormatException('selected photo has invalid size');
        }
        final reader = await file.open();
        late final List<int> prefix;
        try {
          prefix = await reader.read(64);
        } finally {
          await reader.close();
        }
        final contentType = detectImageContentTypeFromPrefix(prefix);
        if (contentType == null) {
          throw const FormatException('selected asset is not a supported image');
        }
        // Content hash is generated within this one user-selected batch;
        // any future durable dedup must also bind owner/session authority.
        final digest = (await sha256.bind(file.openRead()).first).toString();
        if (!fingerprints.add(digest)) {
          duplicates++;
          continue;
        }
        PhotoCaptureEvidence evidence;
        try {
          final tags = await readExifFromFile(file, truncateTags: false);
          evidence = PhotoCaptureEvidence.fromExifTags(tags);
        } catch (_) {
          evidence = const PhotoCaptureEvidence(metadataUnreadable: true);
        }
        good.add(SelectedPhotoImport(
          path: item.path,
          originalFilename: item.name,
          bytes: length,
          contentType: contentType,
          contentSha256: digest,
          evidence: evidence,
        ));
      } catch (_) {
        // Cloud-only/unavailable assets are surfaced as failed, never silently
        // treated as empty photos or re-dated to picker/import time.
        failures.add(item.name);
      }
    }
    return PhotoImportSelection(
      selected: List.unmodifiable(good),
      failedNames: List.unmodifiable(failures),
      duplicates: duplicates,
    );
  }
}
