import 'package:exif/exif.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/photo_import_metadata.dart';

IfdTag _tag(String value) => IfdTag(
  tag: 0,
  tagType: 'ASCII',
  printable: value,
  values: const IfdInts([]),
);

IfdTag _gpsTag(int deg, int min, int sec) => IfdTag(
  tag: 0,
  tagType: 'RATIONAL',
  printable: '$deg, $min, $sec',
  values: IfdRatios([
    Ratio(deg, 1), Ratio(min, 1), Ratio(sec, 1),
  ]),
);

void main() {
  test('timezone evidence yields an exact UTC instant, including midnight crossing', () {
    final result = PhotoCaptureEvidence.fromExifTags({
      'EXIF DateTimeOriginal': _tag('2025:08:09 01:15:00'),
      'EXIF OffsetTimeOriginal': _tag('+08:00'),
      'Image Orientation': IfdTag(
        tag: 0, tagType: 'SHORT', printable: '6', values: const IfdInts([6]),
      ),
    });
    expect(result.localCaptureTime, '2025-08-09 01:15:00');
    expect(result.captureTimeUtc, DateTime.utc(2025, 8, 8, 17, 15));
    expect(result.utcOffsetMinutes, 480);
    expect(result.orientation, 6);
    expect(result.hasGps, false);
  });

  test('historical EXIF captures before Unix epoch are not misdated', () {
    final evidence = PhotoCaptureEvidence.fromExifTags({
      'EXIF DateTimeOriginal': _tag('1965:07:01 10:30:00'),
      'EXIF OffsetTimeOriginal': _tag('+08:00'),
    });
    expect(evidence.captureTimeUtc, DateTime.utc(1965, 7, 1, 2, 30));
  });

  test('explicit offset is authoritative across DST; never infer device timezone', () {
    final east = PhotoCaptureEvidence.fromExifTags({
      'EXIF DateTimeOriginal': _tag('2025:11:02 01:30:00'),
      'EXIF OffsetTimeOriginal': _tag('-04:00'),
    });
    final west = PhotoCaptureEvidence.fromExifTags({
      'EXIF DateTimeOriginal': _tag('2025:11:02 01:30:00'),
      'EXIF OffsetTimeOriginal': _tag('-05:00'),
    });
    expect(east.captureTimeUtc, DateTime.utc(2025, 11, 2, 5, 30));
    expect(west.captureTimeUtc, DateTime.utc(2025, 11, 2, 6, 30));
  });

  test('EXIF capture clock without UTC offset stays non-absolute', () {
    final evidence = PhotoCaptureEvidence.fromExifTags({
      'EXIF DateTimeOriginal': _tag('2024:02:29 16:20:00'),
    });
    expect(evidence.localCaptureTime, '2024-02-29 16:20:00');
    expect(evidence.captureTimeUtc, isNull);
    expect(evidence.hasVerifiedCaptureInstant, false);
  });

  test('no EXIF must never fabricate GPS or capture time', () {
    final evidence = PhotoCaptureEvidence.fromExifTags({});
    expect(evidence.localCaptureTime, isNull);
    expect(evidence.captureTimeUtc, isNull);
    expect(evidence.latitude, isNull);
    expect(evidence.longitude, isNull);
  });

  test('malformed dates and offsets are treated as unknown', () {
    for (final pair in [
      ('2025:02:30 12:00:00', '+08:00'),
      ('0000:00:00 00:00:00', '+08:00'),
      ('2024:12:31 24:30:00', '+08:00'),
      ('2025:03:20 10:00:00', '+24:00'),
    ]) {
      final evidence = PhotoCaptureEvidence.fromExifTags({
        'EXIF DateTimeOriginal': _tag(pair.$1),
        'EXIF OffsetTimeOriginal': _tag(pair.$2),
      });
      expect(evidence.captureTimeUtc, isNull);
    }
  });

  test('complete EXIF GPS fix is preserved only with both direction refs', () {
    final evidence = PhotoCaptureEvidence.fromExifTags({
      'GPS GPSLatitude': _gpsTag(31, 13, 48),
      'GPS GPSLatitudeRef': _tag('N'),
      'GPS GPSLongitude': _gpsTag(121, 28, 26),
      'GPS GPSLongitudeRef': _tag('E'),
    });
    expect(evidence.hasGps, true);
    expect(evidence.latitude!, closeTo(31.23, 0.001));
    expect(evidence.longitude!, closeTo(121.4739, 0.001));

    final partial = PhotoCaptureEvidence.fromExifTags({
      'GPS GPSLatitude': _gpsTag(31, 13, 48),
      'GPS GPSLatitudeRef': _tag('N'),
      'GPS GPSLongitude': _gpsTag(121, 28, 26),
    });
    expect(partial.hasGps, false);
    expect(partial.latitude, isNull);
    expect(partial.longitude, isNull);
  });

  test('invalid GPS degrees, overflow minutes and orientation remain unknown', () {
    final evidence = PhotoCaptureEvidence.fromExifTags({
      'GPS GPSLatitude': _gpsTag(91, 0, 0),
      'GPS GPSLatitudeRef': _tag('S'),
      'GPS GPSLongitude': _gpsTag(121, 60, 0),
      'GPS GPSLongitudeRef': _tag('E'),
      'Image Orientation': IfdTag(
        tag: 0, tagType: 'SHORT', printable: '9', values: const IfdInts([9]),
      ),
    });
    expect(evidence.latitude, isNull);
    expect(evidence.longitude, isNull);
    expect(evidence.orientation, isNull);
  });
}
