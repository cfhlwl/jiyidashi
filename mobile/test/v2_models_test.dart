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
    expect(answered.presentation.label, 'AI 推断（有证据支持）');

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
      expect(stale.presentation.label, '暂不可用');
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
    expect(annual.presentation.label, 'AI 推断（有证据支持）');

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
    expect(chapter.presentation.label, 'AI 推断（有证据支持）');

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
}
