import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/footprint_models.dart';

Map<String, dynamic> _visit({
  Object? latitude = 39.9042,
  Object? longitude = 116.4074,
  Object? address = '北京市东城区',
  Object? category = '办公',
}) {
  return <String, dynamic>{
    'id': '11111111-1111-4111-8111-111111111111',
    'place_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'place_name': '办公室',
    'place_latitude': latitude,
    'place_longitude': longitude,
    'place_address': address,
    'place_category': category,
    'arrived_at': '2026-09-20T00:35:00Z',
    'left_at': '2026-09-20T02:00:00Z',
    'arrived_at_local': '2026-09-20T08:35:00+08:00',
    'left_at_local': '2026-09-20T10:00:00+08:00',
    'confidence': 0.98,
    'visit_source': 'LOCATION_CLUSTER',
    'visit_finalized': true,
  };
}

void main() {
  test('preserves canonical place coordinates/address/category for map rendering', () {
    final day = FootprintDay.fromJson(<String, dynamic>{
      'timezone': 'Asia/Shanghai',
      'day': '2026-09-20',
      'visits': <Map<String, dynamic>>[_visit()],
    });

    expect(day.mappableVisits, hasLength(1));
    final visit = day.mappableVisits.single;
    expect(visit.latitude, 39.9042);
    expect(visit.longitude, 116.4074);
    expect(visit.address, '北京市东城区');
    expect(visit.category, '办公');
  });

  test('allows factual visit without coordinate and excludes it from map', () {
    final day = FootprintDay.fromJson(<String, dynamic>{
      'timezone': 'Asia/Shanghai',
      'day': '2026-09-20',
      'visits': <Map<String, dynamic>>[
        _visit(latitude: null, longitude: null, address: null, category: null),
      ],
    });

    expect(day.visits, hasLength(1));
    expect(day.visits.single.isMappable, isFalse);
    expect(day.mappableVisits, isEmpty);
  });

  test('rejects partial coordinates instead of inventing a map point', () {
    expect(
      () => FootprintDay.fromJson(<String, dynamic>{
        'timezone': 'Asia/Shanghai',
        'day': '2026-09-20',
        'visits': <Map<String, dynamic>>[
          _visit(latitude: 39.9042, longitude: null),
        ],
      }),
      throwsFormatException,
    );
  });

  test('rejects out of range coordinates', () {
    expect(
      () => FootprintVisit.fromJson(_visit(latitude: 91.0)),
      throwsFormatException,
    );
    expect(
      () => FootprintVisit.fromJson(_visit(longitude: 181.0)),
      throwsFormatException,
    );
  });
}
