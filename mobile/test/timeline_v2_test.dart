import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/timeline_models.dart';

void main() {
  test('Timeline parser accepts mixed Memory and Visit authority', () {
    final page = TimelineReadPage.parse({
      'timezone': 'Asia/Shanghai',
      'day': null,
      'items': [
        {
          'kind': 'MEMORY',
          'id': '11111111-1111-4111-8111-111111111111',
          'occurred_at': '2026-09-20T01:00:00Z',
          'ended_at': null,
          'place_id': null,
          'place_name': null,
          'memory_type': 'NOTE',
          'title': '一条记录',
          'content': '正文',
          'source_type': 'USER_TEXT',
          'is_confirmed': true,
          'confidence': 1.0,
          'visit_source': null,
          'visit_finalized': null,
        },
        {
          'kind': 'VISIT',
          'id': '22222222-2222-4222-8222-222222222222',
          'occurred_at': '2026-09-19T01:00:00Z',
          'ended_at': '2026-09-19T02:00:00Z',
          'place_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          'place_name': '家',
          'memory_type': null,
          'title': null,
          'content': null,
          'source_type': null,
          'is_confirmed': null,
          'confidence': 0.9,
          'visit_source': 'LOCATION_CLUSTER',
          'visit_finalized': true,
        },
      ],
      'next_cursor': 'opaque',
    });

    expect(page.items.length, 2);
    expect(page.items.first.isMemory, isTrue);
    expect(page.items.last.isVisit, isTrue);
    expect(page.nextCursor, 'opaque');
  });

  test('Timeline parser fails closed on impossible kind projection', () {
    expect(
      () => TimelineReadPage.parse({
        'timezone': 'Asia/Shanghai',
        'day': null,
        'items': [
          {
            'kind': 'VISIT',
            'id': '22222222-2222-4222-8222-222222222222',
            'occurred_at': '2026-09-19T01:00:00Z',
            'ended_at': null,
            'place_id': null,
            'place_name': null,
            'memory_type': 'NOTE',
            'title': '不应存在',
            'content': '不应存在',
            'is_confirmed': true,
            'confidence': 1.0,
            'visit_finalized': true,
          },
        ],
        'next_cursor': null,
      }),
      throwsA(isA<ProtocolException>()),
    );
  });
}
