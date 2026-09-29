import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/v2/life_models.dart';
import 'package:jiyidashi/v2/people_models.dart';
import 'package:jiyidashi/v2/v2_api.dart';

import 'v2_test_api.dart';

class RecordedV2Call {
  const RecordedV2Call(this.method, this.path, this.body);

  final String method;
  final String path;
  final Map<String, dynamic>? body;
}

class RecordingV2Api extends V2TestApi {
  final calls = <RecordedV2Call>[];

  Map<String, dynamic> get relationship => {
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

  Map<String, dynamic> get personMemoryLink => {
        'id': v2LinkId,
        'person_id': v2PersonId,
        'memory_id': v2MemoryId,
        'relation_kind': 'RELATED',
        'revision': 1,
        'created_at': '2025-03-01T01:00:00Z',
        'updated_at': '2025-03-01T01:00:00Z',
      };

  Map<String, dynamic> get lifeEventEvidence => {
        'link_id': v2LinkId,
        'memory_id': v2MemoryId,
        'memory_type': 'NOTE',
        'title': '团队记录',
        'content': '2025 年加入了新的产品团队。',
        'occurred_at': '2025-03-01T01:00:00Z',
        'source_type': 'USER_TEXT',
        'created_at': '2025-03-01T01:00:00Z',
      };

  Map<String, dynamic> get lifeStageEvent => {
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
      };

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    calls.add(RecordedV2Call(method, path, body));
    final route = Uri.parse(path).path;

    if (method == 'POST' && route == '/people') return person1;
    if (method == 'PATCH' && route == '/people/' + v2PersonId) return person1;
    if (method == 'DELETE' && route == '/people/' + v2PersonId) return {};

    if (method == 'POST' &&
        route == '/people/' + v2PersonId + '/memories/' + v2MemoryId) {
      return personMemoryLink;
    }
    if (method == 'PATCH' &&
        route == '/people/' + v2PersonId + '/memories/' + v2MemoryId) {
      return {...personMemoryLink, 'relation_kind': 'MET', 'revision': 2};
    }
    if (method == 'DELETE' &&
        route == '/people/' + v2PersonId + '/memories/' + v2MemoryId) {
      return {};
    }

    if (method == 'POST' && route == '/people/relationships') {
      return relationship;
    }
    if (method == 'PATCH' && route == '/people/relationships/' + v2LinkId) {
      return {...relationship, 'revision': 2};
    }
    if (method == 'DELETE' && route == '/people/relationships/' + v2LinkId) {
      return {};
    }

    if (method == 'POST' && route == '/life-events') return event;
    if (method == 'PATCH' && route == '/life-events/' + v2EventId) {
      return {...event, 'revision': 3};
    }
    if (method == 'DELETE' && route == '/life-events/' + v2EventId) return {};
    if (method == 'POST' &&
        route == '/life-events/' + v2EventId + '/memories/' + v2MemoryId) {
      return lifeEventEvidence;
    }
    if (method == 'DELETE' &&
        route == '/life-events/' + v2EventId + '/memories/' + v2MemoryId) {
      return {};
    }

    if (method == 'POST' && route == '/life-stages') return stage;
    if (method == 'PATCH' && route == '/life-stages/' + v2StageId) {
      return {...stage, 'revision': 2};
    }
    if (method == 'DELETE' && route == '/life-stages/' + v2StageId) return {};
    if (method == 'POST' &&
        route == '/life-stages/' + v2StageId + '/events/' + v2EventId) {
      return lifeStageEvent;
    }
    if (method == 'DELETE' &&
        route == '/life-stages/' + v2StageId + '/events/' + v2EventId) {
      return {};
    }

    return super.requestV2Json(method, path, body: body);
  }
}

void expectNoClientAuthority(Map<String, dynamic>? body) {
  if (body == null) return;
  for (final forbidden in [
    'user_id',
    'confidence',
    'trust_state',
    'is_confirmed',
    'ai_status',
    'plan_code',
  ]) {
    expect(body.containsKey(forbidden), isFalse, reason: forbidden);
  }
}

void main() {
  test('People Person-Memory and Relationships use canonical owner-implicit routes', () async {
    final raw = RecordingV2Api();
    final api = V2Api(raw);

    final person = V2Person.parse(raw.person1);
    await api.createPerson(displayName: '老张', relationshipLabel: '朋友');
    await api.updatePerson(
      person,
      displayName: '老张',
      relationshipLabel: '朋友',
      note: '备注',
      aliases: const ['张老师'],
    );
    await api.deletePerson(v2PersonId);

    final link = await api.linkPersonMemory(
      personId: v2PersonId,
      memoryId: v2MemoryId,
      relationKind: 'RELATED',
    );
    await api.updatePersonMemory(link: link, relationKind: 'MET');
    await api.unlinkPersonMemory(
      personId: v2PersonId,
      memoryId: v2MemoryId,
    );

    final relationship = await api.createRelationship(
      personAId: v2PersonId,
      personBId: v2Person2Id,
      kind: 'FRIEND',
      note: '长期合作',
    );
    await api.updateRelationship(
      relationship,
      kind: 'FRIEND',
      note: '更新备注',
    );
    await api.deleteRelationship(v2LinkId);

    expect(
      raw.calls.map((call) => call.method + ' ' + Uri.parse(call.path).path),
      containsAllInOrder([
        'POST /people',
        'PATCH /people/' + v2PersonId,
        'DELETE /people/' + v2PersonId,
        'POST /people/' + v2PersonId + '/memories/' + v2MemoryId,
        'PATCH /people/' + v2PersonId + '/memories/' + v2MemoryId,
        'DELETE /people/' + v2PersonId + '/memories/' + v2MemoryId,
        'POST /people/relationships',
        'PATCH /people/relationships/' + v2LinkId,
        'DELETE /people/relationships/' + v2LinkId,
      ]),
    );
    for (final call in raw.calls) {
      expectNoClientAuthority(call.body);
    }
  });

  test('LifeEvent and LifeStage CRUD/evidence links use canonical routes', () async {
    final raw = RecordingV2Api();
    final api = V2Api(raw);
    final event = V2LifeEvent.parse(raw.event);
    final stage = V2LifeStage.parse(raw.stage);

    await api.createLifeEvent(
      kind: 'WORK',
      title: '加入新团队',
      note: '开始新的产品项目',
      startedAt: '2025-03-01T01:00:00Z',
      placeId: v2PlaceId,
    );
    await api.updateLifeEvent(
      event,
      kind: 'WORK',
      title: '加入新团队',
      note: '更新',
      startedAt: '2025-03-01T01:00:00Z',
      placeId: v2PlaceId,
    );
    await api.linkLifeEventMemory(
      eventId: v2EventId,
      memoryId: v2MemoryId,
    );
    await api.unlinkLifeEventMemory(
      eventId: v2EventId,
      memoryId: v2MemoryId,
    );
    await api.deleteLifeEvent(v2EventId);

    await api.createLifeStage(
      kind: 'WORK',
      title: '产品创业阶段',
      startedAt: '2025-01-01T00:00:00Z',
    );
    await api.updateLifeStage(
      stage,
      kind: 'WORK',
      title: '产品创业阶段',
      startedAt: '2025-01-01T00:00:00Z',
    );
    await api.linkLifeStageEvent(
      stageId: v2StageId,
      eventId: v2EventId,
    );
    await api.unlinkLifeStageEvent(
      stageId: v2StageId,
      eventId: v2EventId,
    );
    await api.deleteLifeStage(v2StageId);

    expect(
      raw.calls.map((call) => call.method + ' ' + Uri.parse(call.path).path),
      containsAllInOrder([
        'POST /life-events',
        'PATCH /life-events/' + v2EventId,
        'POST /life-events/' + v2EventId + '/memories/' + v2MemoryId,
        'DELETE /life-events/' + v2EventId + '/memories/' + v2MemoryId,
        'DELETE /life-events/' + v2EventId,
        'POST /life-stages',
        'PATCH /life-stages/' + v2StageId,
        'POST /life-stages/' + v2StageId + '/events/' + v2EventId,
        'DELETE /life-stages/' + v2StageId + '/events/' + v2EventId,
        'DELETE /life-stages/' + v2StageId,
      ]),
    );
    for (final call in raw.calls) {
      expectNoClientAuthority(call.body);
    }
  });

  test('opaque cursors survive query encoding and signed media uses canonical route', () async {
    final raw = RecordingV2Api();
    final api = V2Api(raw);
    const historyCursor = 'opaque/history?a=/+==';
    const photoCursor = 'opaque/photo?b=/+==';
    const stageCursor = 'opaque/stage?c=/+==';

    await api.getLifeHistory(
      startYear: 2020,
      endYear: 2025,
      cursor: historyCursor,
    );
    await api.getAnnualMemoirPhotos('2025', cursor: photoCursor);
    await api.getLifeMemoirStages(cursor: stageCursor);
    await api.getVerifiedMediaDownload(v2MediaId);

    final history = raw.calls.firstWhere(
      (call) => Uri.parse(call.path).path == '/life-history/timeline',
    );
    final photos = raw.calls.firstWhere(
      (call) => Uri.parse(call.path).path == '/memoirs/annual/2025/photos',
    );
    final stages = raw.calls.firstWhere(
      (call) => Uri.parse(call.path).path == '/memoirs/life/stages',
    );
    final media = raw.calls.firstWhere(
      (call) => Uri.parse(call.path).path == '/media/' + v2MediaId + '/download',
    );

    expect(Uri.parse(history.path).queryParameters['cursor'], historyCursor);
    expect(Uri.parse(photos.path).queryParameters['cursor'], photoCursor);
    expect(Uri.parse(stages.path).queryParameters['cursor'], stageCursor);
    expect(media.method, 'POST');
    expectNoClientAuthority(media.body);
  });
}
