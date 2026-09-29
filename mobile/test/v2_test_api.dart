// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:jiyidashi/api_client.dart';

const v2OwnerId = '00000000-0000-4000-8000-000000000001';
const v2PersonId = '11111111-1111-4111-8111-111111111111';
const v2Person2Id = '22222222-2222-4222-8222-222222222222';
const v2StageId = '33333333-3333-4333-8333-333333333333';
const v2EventId = '44444444-4444-4444-8444-444444444444';
const v2MemoryId = '55555555-5555-4555-8555-555555555555';
const v2MemorySourceId = '66666666-6666-4666-8666-666666666666';
const v2LinkId = '77777777-7777-4777-8777-777777777777';
const v2VisitId = '88888888-8888-4888-8888-888888888888';
const v2PlaceId = '99999999-9999-4999-8999-999999999999';
const v2MediaId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

class V2TestApi extends JiYiApiClient {
  V2TestApi({
    this.reasoningStatus = 'ANSWERED',
  }) : super(baseUrl: 'https://v2-test.invalid/v1') {
    accessToken = 'v2-test-token';
    authenticatedUserId = v2OwnerId;
  }

  final String reasoningStatus;

  Map<String, dynamic> get person1 => {
        'id': v2PersonId,
        'display_name': '老张',
        'relationship_label': '朋友',
        'note': '一起做过项目',
        'aliases': ['张老师'],
        'revision': 2,
        'created_at': '2025-01-01T00:00:00Z',
        'updated_at': '2026-09-20T00:00:00Z',
      };

  Map<String, dynamic> get person2 => {
        'id': v2Person2Id,
        'display_name': '小李',
        'relationship_label': '同事',
        'note': null,
        'aliases': const [],
        'revision': 1,
        'created_at': '2025-03-01T00:00:00Z',
        'updated_at': '2026-09-20T00:00:00Z',
      };

  Map<String, dynamic> get event => {
        'id': v2EventId,
        'event_kind': 'WORK',
        'title': '加入新团队',
        'custom_label': null,
        'note': '开始新的产品项目',
        'started_at': '2025-03-01T01:00:00Z',
        'ended_at': null,
        'place_id': v2PlaceId,
        'revision': 2,
        'created_at': '2025-03-01T01:00:00Z',
        'updated_at': '2025-03-02T01:00:00Z',
      };

  Map<String, dynamic> get stage => {
        'id': v2StageId,
        'stage_kind': 'WORK',
        'title': '产品创业阶段',
        'custom_label': null,
        'note': '持续打磨产品',
        'started_at': '2025-01-01T00:00:00Z',
        'ended_at': null,
        'revision': 1,
        'created_at': '2025-01-01T00:00:00Z',
        'updated_at': '2025-01-01T00:00:00Z',
      };

  Map<String, dynamic> get memory => {
        'id': v2MemoryId,
        'user_id': v2OwnerId,
        'memory_type': 'NOTE',
        'title': '团队记录',
        'content': '2025 年加入了新的产品团队。',
        'occurred_at': '2025-03-01T01:00:00Z',
        'source_type': 'USER_TEXT',
        'confidence': 1.0,
        'place_id': v2PlaceId,
        'lat': null,
        'long': null,
        'is_confirmed': true,
        'metadata_json': const {},
        'edit_revision': 1,
        'edited_at': null,
        'created_at': '2025-03-01T01:00:00Z',
      };

  Map<String, dynamic> _provenance() => {
        'gateway_request_id': 'gw-v2-golden',
        'purpose': 'LONG_TERM_REASONING',
        'provider_request_id': 'provider-v2-golden',
        'provider': 'golden-provider',
        'model': 'golden-model',
      };

  Map<String, dynamic> _stageCitation() => {
        'slot': 'stage',
        'kind': 'LIFE_STAGE',
        'life_stage_id': v2StageId,
        'life_event_id': null,
        'memory_id': null,
        'memory_source_id': null,
        'memory_trust_state': null,
      };

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final uri = Uri.parse(path);
    final route = uri.path;

    if (method == 'GET' && route == '/people') return [person1, person2];
    if (method == 'GET' && route == '/people/interactions') {
      return [
        {
          'id': v2LinkId,
          'person_id': v2PersonId,
          'memory_id': v2MemoryId,
          'relation_kind': 'MET',
          'revision': 1,
          'created_at': '2025-03-01T01:00:00Z',
          'updated_at': '2025-03-01T01:00:00Z',
          'person_display_name': '老张',
          'occurred_at': '2025-03-01T01:00:00Z',
        },
      ];
    }
    if (method == 'GET' && route == '/people/' + v2PersonId) return person1;
    if (method == 'GET' && route == '/people/' + v2PersonId + '/memories') {
      return [
        {
          'id': v2LinkId,
          'person_id': v2PersonId,
          'memory_id': v2MemoryId,
          'relation_kind': 'MET',
          'revision': 1,
          'created_at': '2025-03-01T01:00:00Z',
          'updated_at': '2025-03-01T01:00:00Z',
          'occurred_at': '2025-03-01T01:00:00Z',
          'memory_title': '团队记录',
          'memory_content': '2025 年加入了新的产品团队。',
          'memory_type': 'NOTE',
        },
      ];
    }
    if (method == 'GET' && route == '/people/' + v2PersonId + '/relationships') {
      return [
        {
          'relationship_id': v2LinkId,
          'relationship_kind': 'FRIEND',
          'custom_label': null,
          'note': '长期合作',
          'revision': 1,
          'other_person': {
            'id': v2Person2Id,
            'display_name': '小李',
          },
          'created_at': '2025-01-01T00:00:00Z',
          'updated_at': '2025-01-01T00:00:00Z',
        },
      ];
    }
    if (method == 'GET' && route == '/people/' + v2PersonId + '/known-duration') {
      return {
        'status': 'KNOWN_SINCE_MET',
        'person_id': v2PersonId,
        'display_name': '老张',
        'as_of': '2026-09-29T00:00:00Z',
        'at_least_since_at': '2025-03-01T01:00:00Z',
        'elapsed_days': 577,
        'earliest_related_at': null,
        'evidence': {
          'person_memory_link_id': v2LinkId,
          'memory_id': v2MemoryId,
          'memory_source_id': v2MemorySourceId,
          'relation_kind': 'MET',
          'trust_state': 'EVIDENCE_SUPPORTED',
          'occurred_at': '2025-03-01T01:00:00Z',
        },
      };
    }
    if (method == 'GET' && route == '/timeline') return [memory];
    if (method == 'GET' && route == '/location/places') {
      return [
        {
          'id': v2PlaceId,
          'name': '上海办公室',
          'name_source': 'USER',
          'address': '上海市测试路 1 号',
          'category': 'OFFICE',
          'visit_count': 5,
          'first_visited_at': '2025-01-01T00:00:00Z',
          'last_visited_at': '2026-09-20T00:00:00Z',
        },
      ];
    }
    if (method == 'GET' &&
        route == '/graph/neighborhood/PERSON/' + v2PersonId) {
      return {
        'center': {
          'kind': 'PERSON',
          'id': v2PersonId,
          'label': '老张',
          'occurred_at': null,
        },
        'nodes': [
          {
            'kind': 'PERSON',
            'id': v2Person2Id,
            'label': '小李',
            'occurred_at': null,
          },
        ],
        'edges': [
          {
            'edge_kind': 'PERSON_RELATIONSHIP',
            'source': {
              'kind': 'PERSON',
              'id': v2PersonId,
              'label': '老张',
              'occurred_at': null,
            },
            'target': {
              'kind': 'PERSON',
              'id': v2Person2Id,
              'label': '小李',
              'occurred_at': null,
            },
            'authority_ref': v2LinkId,
            'metadata': {
              'relationship_kind': 'FRIEND',
              'custom_label': null,
              'relation_kind': null,
              'recorded_at': null,
            },
          },
        ],
        'truncated': false,
      };
    }

    if (method == 'GET' && route == '/life-events') return [event];
    if (method == 'GET' && route == '/life-events/' + v2EventId) return event;
    if (method == 'GET' && route == '/life-events/' + v2EventId + '/memories') {
      return [
        {
          'link_id': v2LinkId,
          'memory_id': v2MemoryId,
          'memory_type': 'NOTE',
          'title': '团队记录',
          'content': '2025 年加入了新的产品团队。',
          'occurred_at': '2025-03-01T01:00:00Z',
          'source_type': 'USER_TEXT',
          'created_at': '2025-03-01T01:00:00Z',
        },
      ];
    }

    if (method == 'GET' && route == '/life-stages') return [stage];
    if (method == 'GET' && route == '/life-stages/' + v2StageId) return stage;
    if (method == 'GET' && route == '/life-stages/' + v2StageId + '/events') {
      return [
        {
          'link_id': v2LinkId,
          'life_event_id': v2EventId,
          'event_kind': 'WORK',
          'title': '加入新团队',
          'custom_label': null,
          'note': '开始新的产品项目',
          'started_at': '2025-03-01T01:00:00Z',
          'ended_at': null,
          'place_id': v2PlaceId,
          'created_at': '2025-03-01T01:00:00Z',
        },
      ];
    }
    if (method == 'POST' &&
        route == '/life-stages/' + v2StageId + '/reason') {
      if (reasoningStatus == 'ANSWERED') {
        return {
          'status': 'ANSWERED',
          'answer': '这个阶段持续围绕产品开发，并由明确阶段记录支持。',
          'citations': [_stageCitation()],
          'provider_error_code': null,
          'ai_provenance': _provenance(),
        };
      }
      if (reasoningStatus == 'EVIDENCE_INCOMPLETE') {
        return {
          'status': 'EVIDENCE_INCOMPLETE',
          'answer': null,
          'citations': const [],
          'provider_error_code': null,
          'ai_provenance': null,
        };
      }
      return {
        'status': 'PROVIDER_FAILED',
        'answer': null,
        'citations': const [],
        'provider_error_code': 'AI_PROVIDER_FAILED',
        'ai_provenance': null,
      };
    }

    if (method == 'GET' && route == '/life-history/timeline') {
      final start = int.parse(uri.queryParameters['start_year'] ?? '2025');
      final end = int.parse(uri.queryParameters['end_year'] ?? '2025');
      return {
        'timezone': 'Asia/Shanghai',
        'start_year': start,
        'end_year': end,
        'as_of': '2026-09-29T00:00:00Z',
        'items': [
          {
            'kind': 'LIFE_EVENT',
            'occurred_at': '2025-03-01T01:00:00Z',
            'title': '加入新团队',
            'custom_label': null,
            'life_event_id': v2EventId,
            'event_kind': 'WORK',
            'event_ended_at': null,
            'place_id': v2PlaceId,
            'life_stage_id': null,
            'stage_kind': null,
          },
        ],
        'next_cursor': null,
      };
    }

    if (method == 'POST' && route == '/memoirs/annual') {
      final target = body?['target_year']?.toString() ?? '2025';
      return {
        'status': 'MEMOIR_READY',
        'target_year': target,
        'timezone': 'Asia/Shanghai',
        'narrative_status': 'ANNUAL_SUMMARY_READY',
        'narrative': '这一年，你开始了新的产品阶段，并留下了明确记录。',
        'narrative_citations': [
          {
            'slot': 'memory-1',
            'kind': 'MEMORY',
            'memory_id': v2MemoryId,
            'visit_id': null,
            'trust_state': 'EVIDENCE_SUPPORTED',
          },
        ],
        'timeline_items': [
          {
            'kind': 'LIFE_EVENT',
            'occurred_at': '2025-03-01T01:00:00Z',
            'title': '加入新团队',
            'custom_label': null,
            'life_event_id': v2EventId,
            'event_kind': 'WORK',
            'event_ended_at': null,
            'place_id': v2PlaceId,
            'life_stage_id': null,
            'stage_kind': null,
          },
        ],
        'timeline_next_cursor': null,
        'photo_items': [
          {
            'memory_id': v2MemoryId,
            'media_id': v2MediaId,
            'occurred_at': '2025-03-01T01:00:00Z',
            'title': '团队合影',
            'content_type': 'image/jpeg',
          },
        ],
        'photo_next_cursor': null,
      };
    }
    if (method == 'GET' && route == '/memoirs/annual/2025/photos') {
      return {
        'timezone': 'Asia/Shanghai',
        'target_year': '2025',
        'items': const [],
        'next_cursor': null,
      };
    }
    if (method == 'POST' && route == '/media/' + v2MediaId + '/download') {
      return {
        'media_id': v2MediaId,
        'download': {
          'method': 'GET',
          'url': 'https://example.test/signed-photo.jpg',
          'headers': const <String, dynamic>{},
          'expires_at': '2026-09-29T01:00:00Z',
        },
      };
    }

    if (method == 'GET' && route == '/memoirs/life/stages') {
      return {
        'items': [
          {
            'life_stage_id': v2StageId,
            'stage_kind': 'WORK',
            'title': '产品创业阶段',
            'custom_label': null,
            'started_at': '2025-01-01T00:00:00Z',
            'ended_at': null,
          },
        ],
        'next_cursor': null,
      };
    }
    if (method == 'POST' && route == '/memoirs/life/stages/' + v2StageId) {
      return {
        'status': 'CHAPTER_READY',
        'life_stage_id': v2StageId,
        'reasoning_status': 'ANSWERED',
        'narrative': '这一阶段以产品开发为主线，形成了持续的明确记录。',
        'citations': [_stageCitation()],
      };
    }

    if (method == 'GET' && route == '/people/relationships/' + v2LinkId) {
      return {
        'id': v2LinkId,
        'person_a_id': v2PersonId,
        'person_b_id': v2Person2Id,
        'relationship_kind': 'FRIEND',
        'custom_label': null,
        'note': '长期合作',
        'revision': 1,
        'created_at': '2025-01-01T00:00:00Z',
        'updated_at': '2025-01-01T00:00:00Z',
      };
    }

    throw StateError('Unhandled V2 test request: ' + method + ' ' + path);
  }
}
