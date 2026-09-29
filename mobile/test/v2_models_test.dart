import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/v2/graph_models.dart';
import 'package:jiyidashi/v2/life_models.dart';
import 'package:jiyidashi/v2/memoir_models.dart';
import 'package:jiyidashi/v2/people_models.dart';

const personId = '11111111-1111-4111-8111-111111111111';
const person2Id = '22222222-2222-4222-8222-222222222222';
const stageId = '33333333-3333-4333-8333-333333333333';
const eventId = '44444444-4444-4444-8444-444444444444';
const memoryId = '55555555-5555-4555-8555-555555555555';
const sourceId = '66666666-6666-4666-8666-666666666666';
const linkId = '77777777-7777-4777-8777-777777777777';
const visitId = '88888888-8888-4888-8888-888888888888';

Map<String, dynamic> provenance() => {
      'gateway_request_id': 'gw-1',
      'purpose': 'LONG_TERM_REASONING',
      'provider_request_id': 'provider-1',
      'provider': 'test-provider',
      'model': 'test-model',
    };

Map<String, dynamic> stageCitation({String slot = 'stage'}) => {
      'slot': slot,
      'kind': 'LIFE_STAGE',
      'life_stage_id': stageId,
      'life_event_id': null,
      'memory_id': null,
      'memory_source_id': null,
      'memory_trust_state': null,
    };

Map<String, dynamic> memoryCitation({
  String slot = 'memory',
  String trust = 'EVIDENCE_SUPPORTED',
}) =>
    {
      'slot': slot,
      'kind': 'MEMORY',
      'life_stage_id': stageId,
      'life_event_id': eventId,
      'memory_id': memoryId,
      'memory_source_id': sourceId,
      'memory_trust_state': trust,
    };

void main() {
  test('People parser rejects duplicate aliases and ids', () {
    final row = {
      'id': personId,
      'display_name': '老张',
      'relationship_label': '朋友',
      'note': null,
      'aliases': ['张老师'],
      'revision': 1,
      'created_at': '2025-01-01T00:00:00Z',
      'updated_at': '2025-01-01T00:00:00Z',
    };
    expect(V2Person.parse(row).displayName, '老张');
    expect(
      () => V2Person.parse({...row, 'aliases': ['张老师', '张老师']}),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      () => parsePersonList([row, row]),
      throwsA(isA<ProtocolException>()),
    );
  });

  test('Graph rejects endpoint projection drift and duplicate authority refs', () {
    final center = {
      'kind': 'PERSON',
      'id': personId,
      'label': '老张',
      'occurred_at': null,
    };
    final node = {
      'kind': 'PERSON',
      'id': person2Id,
      'label': '小李',
      'occurred_at': null,
    };
    final edge = {
      'edge_kind': 'PERSON_RELATIONSHIP',
      'source': center,
      'target': node,
      'authority_ref': linkId,
      'metadata': {
        'relationship_kind': 'FRIEND',
        'custom_label': null,
        'relation_kind': null,
        'recorded_at': null,
      },
    };
    final parsed = V2GraphNeighborhood.parse(
      {
        'center': center,
        'nodes': [node],
        'edges': [edge],
        'truncated': false,
      },
      expectedKind: 'PERSON',
      expectedId: personId,
    );
    expect(parsed.edges.single.kind, 'PERSON_RELATIONSHIP');

    expect(
      () => V2GraphNeighborhood.parse(
        {
          'center': center,
          'nodes': [node],
          'edges': [
            {
              ...edge,
              'target': {...node, 'label': '伪造显示名'},
            },
          ],
          'truncated': false,
        },
        expectedKind: 'PERSON',
        expectedId: personId,
      ),
      throwsA(isA<ProtocolException>()),
    );

    expect(
      () => V2GraphNeighborhood.parse(
        {
          'center': center,
          'nodes': [node],
          'edges': [edge, edge],
          'truncated': false,
        },
        expectedKind: 'PERSON',
        expectedId: personId,
      ),
      throwsA(isA<ProtocolException>()),
    );
  });

  test('Known Duration never accepts guessed duration without MET evidence', () {
    final known = V2KnownDuration.parse(
      {
        'status': 'KNOWN_SINCE_MET',
        'person_id': personId,
        'display_name': '老张',
        'as_of': '2026-09-29T00:00:00+08:00',
        'at_least_since_at': '2020-01-01T00:00:00+08:00',
        'elapsed_days': 2463,
        'earliest_related_at': null,
        'evidence': {
          'person_memory_link_id': linkId,
          'memory_id': memoryId,
          'memory_source_id': sourceId,
          'relation_kind': 'MET',
          'trust_state': 'EVIDENCE_SUPPORTED',
          'occurred_at': '2020-01-01T00:00:00+08:00',
        },
      },
      personId: personId,
    );
    expect(known.elapsedDays, 2463);

    expect(
      () => V2KnownDuration.parse(
        {
          'status': 'NO_TRUSTED_EVIDENCE',
          'person_id': personId,
          'display_name': '老张',
          'as_of': '2026-09-29T00:00:00+08:00',
          'at_least_since_at': null,
          'elapsed_days': 100,
          'earliest_related_at': null,
          'evidence': null,
        },
        personId: personId,
      ),
      throwsA(isA<ProtocolException>()),
    );
  });

  test('Long-term Reasoning locks citation trust, slots and provenance', () {
    final answered = V2LongTermReasoning.parse(
      {
        'status': 'ANSWERED',
        'answer': '这个阶段持续围绕产品开发。',
        'citations': [stageCitation(), memoryCitation()],
        'provider_error_code': null,
        'ai_provenance': provenance(),
      },
      stageId: stageId,
    );
    expect(answered.presentation.label, 'AI 整理');

    for (final trust in ['INFERENCE_ONLY', 'NO_EVIDENCE']) {
      expect(
        () => V2LongTermReasoning.parse(
          {
            'status': 'ANSWERED',
            'answer': '不应通过',
            'citations': [memoryCitation(trust: trust)],
            'provider_error_code': null,
            'ai_provenance': provenance(),
          },
          stageId: stageId,
        ),
        throwsA(isA<ProtocolException>()),
      );
    }

    expect(
      () => V2LongTermReasoning.parse(
        {
          'status': 'ANSWERED',
          'answer': '重复 slot',
          'citations': [
            stageCitation(slot: 'dup'),
            memoryCitation(slot: 'dup'),
          ],
          'provider_error_code': null,
          'ai_provenance': provenance(),
        },
        stageId: stageId,
      ),
      throwsA(isA<ProtocolException>()),
    );

    for (final status in [
      'NO_ANSWERABLE_EVIDENCE',
      'EVIDENCE_INCOMPLETE',
      'PROVIDER_FAILED',
    ]) {
      expect(
        () => V2LongTermReasoning.parse(
          {
            'status': status,
            'answer': null,
            'citations': const [],
            'provider_error_code':
                status == 'PROVIDER_FAILED' ? 'AI_PROVIDER_FAILED' : null,
            'ai_provenance': provenance(),
          },
          stageId: stageId,
        ),
        throwsA(isA<ProtocolException>()),
      );
    }

    for (final status in ['MALFORMED_PROVIDER_OUTPUT', 'INVALID_CITATION']) {
      expect(
        () => V2LongTermReasoning.parse(
          {
            'status': status,
            'answer': null,
            'citations': const [],
            'provider_error_code': null,
            'ai_provenance': null,
          },
          stageId: stageId,
        ),
        throwsA(isA<ProtocolException>()),
      );
    }

    for (final provenanceValue in [null, provenance()]) {
      final stale = V2LongTermReasoning.parse(
        {
          'status': 'EVIDENCE_CHANGED_DURING_GENERATION',
          'answer': null,
          'citations': const [],
          'provider_error_code': null,
          'ai_provenance': provenanceValue,
        },
        stageId: stageId,
      );
      expect(stale.presentation.label, '暂时无法整理');
    }
  });

  test('Annual and Life Memoir keep citation matrices fail closed', () {
    final annual = V2AnnualMemoir.parse(
      {
        'status': 'MEMOIR_READY',
        'target_year': '2025',
        'timezone': 'Asia/Shanghai',
        'narrative_status': 'ANNUAL_SUMMARY_READY',
        'narrative': '这一年有多条明确记录。',
        'narrative_citations': [
          {
            'slot': 'm1',
            'kind': 'MEMORY',
            'memory_id': memoryId,
            'visit_id': null,
            'trust_state': 'CONFIRMED',
          },
        ],
        'timeline_items': const [],
        'timeline_next_cursor': null,
        'photo_items': const [],
        'photo_next_cursor': null,
      },
      year: '2025',
    );
    expect(annual.presentation.label, 'AI 整理');

    expect(
      () => V2AnnualMemoir.parse(
        {
          'status': 'MEMOIR_READY',
          'target_year': '2025',
          'timezone': 'Asia/Shanghai',
          'narrative_status': 'ANNUAL_SUMMARY_READY',
          'narrative': '不应通过',
          'narrative_citations': [
            {
              'slot': 'bad',
              'kind': 'MEMORY',
              'memory_id': memoryId,
              'visit_id': null,
              'trust_state': 'NO_EVIDENCE',
            },
          ],
          'timeline_items': const [],
          'timeline_next_cursor': null,
          'photo_items': const [],
          'photo_next_cursor': null,
        },
        year: '2025',
      ),
      throwsA(isA<ProtocolException>()),
    );

    final chapter = V2LifeMemoirChapter.parse(
      {
        'status': 'CHAPTER_READY',
        'life_stage_id': stageId,
        'reasoning_status': 'ANSWERED',
        'narrative': '阶段章节。',
        'citations': [memoryCitation()],
      },
      stageId: stageId,
    );
    expect(chapter.presentation.label, 'AI 整理');

    expect(
      () => V2LifeMemoirChapter.parse(
        {
          'status': 'CHAPTER_PARTIAL',
          'life_stage_id': stageId,
          'reasoning_status': 'EVIDENCE_INCOMPLETE',
          'narrative': null,
          'citations': [stageCitation()],
        },
        stageId: stageId,
      ),
      throwsA(isA<ProtocolException>()),
    );
  });

  test('Known Duration accepts related-only and no-trusted states without guessing', () {
    final related = V2KnownDuration.parse(
      {
        'status': 'RELATED_EVIDENCE_ONLY',
        'person_id': personId,
        'display_name': '老张',
        'as_of': '2026-09-29T00:00:00+08:00',
        'at_least_since_at': null,
        'elapsed_days': null,
        'earliest_related_at': '2021-02-03T04:05:06+08:00',
        'evidence': {
          'person_memory_link_id': linkId,
          'memory_id': memoryId,
          'memory_source_id': sourceId,
          'relation_kind': 'RELATED',
          'trust_state': 'CONFIRMED',
          'occurred_at': '2021-02-03T04:05:06+08:00',
        },
      },
      personId: personId,
    );
    expect(related.elapsedDays, isNull);
    expect(related.earliestRelatedAt, '2021-02-03T04:05:06+08:00');

    final none = V2KnownDuration.parse(
      {
        'status': 'NO_TRUSTED_EVIDENCE',
        'person_id': personId,
        'display_name': '老张',
        'as_of': '2026-09-29T00:00:00+08:00',
        'at_least_since_at': null,
        'elapsed_days': null,
        'earliest_related_at': null,
        'evidence': null,
      },
      personId: personId,
    );
    expect(none.elapsedDays, isNull);
    expect(none.evidence, isNull);
  });

  test('Cross-year History preserves opaque cursor and typed boundaries', () {
    const opaque = 'opaque/next?token=a%2Fb+1==';
    final page = V2LifeHistoryPage.parse(
      {
        'timezone': 'Asia/Shanghai',
        'start_year': 2020,
        'end_year': 2026,
        'as_of': '2026-09-29T00:00:00+08:00',
        'items': [
          {
            'kind': 'LIFE_EVENT',
            'occurred_at': '2025-03-01T01:00:00Z',
            'title': '加入新团队',
            'custom_label': null,
            'life_event_id': eventId,
            'event_kind': 'WORK',
            'event_ended_at': null,
            'place_id': null,
            'life_stage_id': null,
            'stage_kind': null,
          },
          {
            'kind': 'LIFE_STAGE_STARTED',
            'occurred_at': '2024-01-01T00:00:00Z',
            'title': '产品阶段',
            'custom_label': null,
            'life_event_id': null,
            'event_kind': null,
            'event_ended_at': null,
            'place_id': null,
            'life_stage_id': stageId,
            'stage_kind': 'WORK',
          },
          {
            'kind': 'LIFE_STAGE_ENDED',
            'occurred_at': '2025-12-31T23:59:00Z',
            'title': '产品阶段',
            'custom_label': null,
            'life_event_id': null,
            'event_kind': null,
            'event_ended_at': null,
            'place_id': null,
            'life_stage_id': stageId,
            'stage_kind': 'WORK',
          },
        ],
        'next_cursor': opaque,
      },
      startYear: 2020,
      endYear: 2026,
    );
    expect(page.nextCursor, opaque);
    expect(page.items.map((item) => item.kind), [
      'LIFE_EVENT',
      'LIFE_STAGE_STARTED',
      'LIFE_STAGE_ENDED',
    ]);
  });

  test('Annual Memoir accepts ready partial empty and rejects Visit trust/duplicate slots', () {
    V2AnnualMemoir base({
      required String status,
      required String narrativeStatus,
      String? narrative,
      List<Map<String, dynamic>> citations = const [],
      List<Map<String, dynamic>> timeline = const [],
    }) =>
        V2AnnualMemoir.parse(
          {
            'status': status,
            'target_year': '2025',
            'timezone': 'Asia/Shanghai',
            'narrative_status': narrativeStatus,
            'narrative': narrative,
            'narrative_citations': citations,
            'timeline_items': timeline,
            'timeline_next_cursor': null,
            'photo_items': const [],
            'photo_next_cursor': null,
          },
          year: '2025',
        );

    expect(
      base(
        status: 'MEMOIR_READY',
        narrativeStatus: 'ANNUAL_SUMMARY_READY',
        narrative: '年度叙事',
        citations: [
          {
            'slot': 'm1',
            'kind': 'MEMORY',
            'memory_id': memoryId,
            'visit_id': null,
            'trust_state': 'CONFIRMED',
          },
        ],
      ).status,
      'MEMOIR_READY',
    );

    expect(
      base(
        status: 'MEMOIR_PARTIAL',
        narrativeStatus: 'SUMMARY_INCOMPLETE',
        timeline: [
          {
            'kind': 'LIFE_EVENT',
            'occurred_at': '2025-03-01T01:00:00Z',
            'title': '事件',
            'custom_label': null,
            'life_event_id': eventId,
            'event_kind': 'WORK',
            'event_ended_at': null,
            'place_id': null,
            'life_stage_id': null,
            'stage_kind': null,
          },
        ],
      ).status,
      'MEMOIR_PARTIAL',
    );

    expect(
      base(
        status: 'MEMOIR_EMPTY',
        narrativeStatus: 'NO_SUMMARIZABLE_EVIDENCE',
      ).status,
      'MEMOIR_EMPTY',
    );

    expect(
      () => base(
        status: 'MEMOIR_READY',
        narrativeStatus: 'ANNUAL_SUMMARY_READY',
        narrative: '错误 Visit trust',
        citations: [
          {
            'slot': 'v1',
            'kind': 'VISIT',
            'memory_id': null,
            'visit_id': visitId,
            'trust_state': 'CONFIRMED',
          },
        ],
      ),
      throwsA(isA<ProtocolException>()),
    );

    expect(
      () => base(
        status: 'MEMOIR_READY',
        narrativeStatus: 'ANNUAL_SUMMARY_READY',
        narrative: '重复 slot',
        citations: [
          {
            'slot': 'dup',
            'kind': 'MEMORY',
            'memory_id': memoryId,
            'visit_id': null,
            'trust_state': 'CONFIRMED',
          },
          {
            'slot': 'dup',
            'kind': 'VISIT',
            'memory_id': null,
            'visit_id': visitId,
            'trust_state': null,
          },
        ],
      ),
      throwsA(isA<ProtocolException>()),
    );
  });

  test('Life Memoir chapter accepts ready partial empty only with matching payload', () {
    final ready = V2LifeMemoirChapter.parse(
      {
        'status': 'CHAPTER_READY',
        'life_stage_id': stageId,
        'reasoning_status': 'ANSWERED',
        'narrative': '章节叙事',
        'citations': [stageCitation()],
      },
      stageId: stageId,
    );
    expect(ready.status, 'CHAPTER_READY');

    final partial = V2LifeMemoirChapter.parse(
      {
        'status': 'CHAPTER_PARTIAL',
        'life_stage_id': stageId,
        'reasoning_status': 'EVIDENCE_INCOMPLETE',
        'narrative': null,
        'citations': const [],
      },
      stageId: stageId,
    );
    expect(partial.status, 'CHAPTER_PARTIAL');

    final empty = V2LifeMemoirChapter.parse(
      {
        'status': 'CHAPTER_EMPTY',
        'life_stage_id': stageId,
        'reasoning_status': 'NO_ANSWERABLE_EVIDENCE',
        'narrative': null,
        'citations': const [],
      },
      stageId: stageId,
    );
    expect(empty.status, 'CHAPTER_EMPTY');
  });

  test('Annual photo cursor and signed media stay canonical', () {
    const opaque = 'photo:opaque/next?x=1+2==';
    final photos = V2AnnualMemoirPhotoPage.parse(
      {
        'timezone': 'Asia/Shanghai',
        'target_year': '2025',
        'items': const [],
        'next_cursor': opaque,
      },
      year: '2025',
    );
    expect(photos.nextCursor, opaque);

    final signed = V2SignedMediaDownload.parse(
      {
        'media_id': memoryId,
        'download': {
          'method': 'GET',
          'url': 'https://media.example.test/signed/photo',
          'headers': {'X-Test': '1'},
          'expires_at': '2026-09-29T01:00:00Z',
        },
      },
      mediaId: memoryId,
    );
    expect(signed.method, 'GET');
    expect(signed.url.scheme, 'https');

    expect(
      () => V2SignedMediaDownload.parse(
        {
          'media_id': memoryId,
          'download': {
            'method': 'GET',
            'url': 'http://media.example.test/plain',
            'headers': const {},
            'expires_at': '2026-09-29T01:00:00Z',
          },
        },
        mediaId: memoryId,
      ),
      throwsA(isA<ProtocolException>()),
    );

    expect(
      () => V2SignedMediaDownload.parse(
        {
          'media_id': visitId,
          'download': {
            'method': 'GET',
            'url': 'https://media.example.test/signed/photo',
            'headers': const {},
            'expires_at': '2026-09-29T01:00:00Z',
          },
        },
        mediaId: memoryId,
      ),
      throwsA(isA<ProtocolException>()),
    );
  });


  test('Known Duration rejects non-authoritative trust states', () {
    for (final trust in ['INFERENCE_ONLY', 'NO_EVIDENCE']) {
      expect(
        () => V2KnownDuration.parse(
          {
            'status': 'KNOWN_SINCE_MET',
            'person_id': personId,
            'display_name': '老张',
            'as_of': '2026-09-29T00:00:00+08:00',
            'at_least_since_at': '2020-01-01T00:00:00+08:00',
            'elapsed_days': 2463,
            'earliest_related_at': null,
            'evidence': {
              'person_memory_link_id': linkId,
              'memory_id': memoryId,
              'memory_source_id': sourceId,
              'relation_kind': 'MET',
              'trust_state': trust,
              'occurred_at': '2020-01-01T00:00:00+08:00',
            },
          },
          personId: personId,
        ),
        throwsA(isA<ProtocolException>()),
        reason: trust,
      );
    }
  });

  test('LifeStageEvent rejects impossible nested event projections', () {
    Map<String, dynamic> row({
      String kind = 'WORK',
      String? customLabel,
      String startedAt = '2025-03-01T01:00:00Z',
      String? endedAt,
    }) =>
        {
          'link_id': linkId,
          'life_event_id': eventId,
          'event_kind': kind,
          'title': '阶段事件',
          'custom_label': customLabel,
          'note': null,
          'started_at': startedAt,
          'ended_at': endedAt,
          'place_id': null,
          'created_at': '2025-03-01T01:00:00Z',
        };

    expect(V2LifeStageEvent.parse(row()).eventKind, 'WORK');
    expect(
      () => V2LifeStageEvent.parse(row(kind: 'OTHER')),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      () => V2LifeStageEvent.parse(row(customLabel: '不应存在')),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      () => V2LifeStageEvent.parse(
        row(
          startedAt: '2025-03-02T01:00:00Z',
          endedAt: '2025-03-01T01:00:00Z',
        ),
      ),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      V2LifeStageEvent.parse(
        row(kind: 'OTHER', customLabel: '重要节点'),
      ).customLabel,
      '重要节点',
    );
  });

  test('Life History rejects impossible event/stage projection matrices', () {
    Map<String, dynamic> eventRow({
      String eventKind = 'WORK',
      String? customLabel,
      String? endedAt,
    }) =>
        {
          'kind': 'LIFE_EVENT',
          'occurred_at': '2025-03-01T01:00:00Z',
          'title': '事件',
          'custom_label': customLabel,
          'life_event_id': eventId,
          'event_kind': eventKind,
          'event_ended_at': endedAt,
          'place_id': null,
          'life_stage_id': null,
          'stage_kind': null,
        };

    Map<String, dynamic> stageRow({
      String stageKind = 'WORK',
      String? customLabel,
      Object? eventEndedAt,
      Object? placeId,
    }) =>
        {
          'kind': 'LIFE_STAGE_STARTED',
          'occurred_at': '2025-01-01T00:00:00Z',
          'title': '阶段',
          'custom_label': customLabel,
          'life_event_id': null,
          'event_kind': null,
          'event_ended_at': eventEndedAt,
          'place_id': placeId,
          'life_stage_id': stageId,
          'stage_kind': stageKind,
        };

    expect(V2LifeHistoryItem.parse(eventRow()).kind, 'LIFE_EVENT');
    expect(
      () => V2LifeHistoryItem.parse(eventRow(eventKind: 'OTHER')),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      () => V2LifeHistoryItem.parse(eventRow(customLabel: '不应存在')),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      () => V2LifeHistoryItem.parse(
        eventRow(endedAt: '2025-02-28T23:00:00Z'),
      ),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      V2LifeHistoryItem.parse(
        eventRow(eventKind: 'OTHER', customLabel: '其他事件'),
      ).customLabel,
      '其他事件',
    );

    expect(V2LifeHistoryItem.parse(stageRow()).kind, 'LIFE_STAGE_STARTED');
    expect(
      () => V2LifeHistoryItem.parse(stageRow(stageKind: 'OTHER')),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      () => V2LifeHistoryItem.parse(stageRow(customLabel: '不应存在')),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      () => V2LifeHistoryItem.parse(
        stageRow(eventEndedAt: '2025-01-02T00:00:00Z'),
      ),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      () => V2LifeHistoryItem.parse(stageRow(placeId: person2Id)),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      V2LifeHistoryItem.parse(
        stageRow(stageKind: 'OTHER', customLabel: '其他阶段'),
      ).customLabel,
      '其他阶段',
    );
  });

  test('Life Memoir stage rejects impossible nested stage projections', () {
    Map<String, dynamic> row({
      String kind = 'WORK',
      String? customLabel,
      String startedAt = '2025-01-01T00:00:00Z',
      String? endedAt,
    }) =>
        {
          'life_stage_id': stageId,
          'stage_kind': kind,
          'title': '阶段',
          'custom_label': customLabel,
          'started_at': startedAt,
          'ended_at': endedAt,
        };

    expect(V2LifeMemoirStage.parse(row()).stageKind, 'WORK');
    expect(
      () => V2LifeMemoirStage.parse(row(kind: 'OTHER')),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      () => V2LifeMemoirStage.parse(row(customLabel: '不应存在')),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      () => V2LifeMemoirStage.parse(
        row(
          startedAt: '2025-02-01T00:00:00Z',
          endedAt: '2025-01-01T00:00:00Z',
        ),
      ),
      throwsA(isA<ProtocolException>()),
    );
    expect(
      V2LifeMemoirStage.parse(
        row(kind: 'OTHER', customLabel: '其他阶段'),
      ).customLabel,
      '其他阶段',
    );
  });

}
