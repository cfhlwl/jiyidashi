import '../api_client.dart';
import 'graph_models.dart';
import 'life_models.dart';
import 'memoir_models.dart';
import 'people_models.dart';
import 'v2_common.dart';

class V2Api {
  V2Api(this.api);

  final JiYiApiClient api;

  Future<Object?> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) =>
      api.requestV2Json(method, path, body: body);

  String _query(String path, Map<String, String> query) =>
      Uri(path: path, queryParameters: query).toString();

  Future<List<V2Person>> listPeople({int limit = 50}) async {
    final bounded = limit.clamp(1, 100);
    final raw = await _request('GET', _query('/people', {'limit': '$bounded'}));
    return parsePersonList(raw, limit: bounded);
  }

  Future<V2Person> createPerson({
    required String displayName,
    String? relationshipLabel,
    String? note,
  }) async {
    final raw = await _request('POST', '/people', body: {
      'display_name': displayName.trim(),
      'relationship_label': relationshipLabel?.trim().isEmpty == true
          ? null
          : relationshipLabel?.trim(),
      'note': note?.trim().isEmpty == true ? null : note?.trim(),
    });
    return V2Person.parse(raw);
  }

  Future<V2Person> getPerson(String personId) async {
    final id = v2PathId(personId, '人物');
    final raw = await _request('GET', '/people/' + id);
    return V2Person.parse(raw, expectedId: personId);
  }

  Future<V2Person> updatePerson(
    V2Person person, {
    required String displayName,
    String? relationshipLabel,
    String? note,
    required List<String> aliases,
  }) async {
    final id = v2PathId(person.id, '人物');
    final raw = await _request('PATCH', '/people/' + id, body: {
      'expected_revision': person.revision,
      'display_name': displayName.trim(),
      'relationship_label': relationshipLabel?.trim().isEmpty == true
          ? null
          : relationshipLabel?.trim(),
      'note': note?.trim().isEmpty == true ? null : note?.trim(),
      'aliases': aliases.map((item) => item.trim()).toList(growable: false),
    });
    return V2Person.parse(raw, expectedId: person.id);
  }

  Future<void> deletePerson(String personId) async {
    await _request('DELETE', '/people/' + v2PathId(personId, '人物'));
  }

  Future<List<V2MemoryPickerItem>> listMemoryChoices({int limit = 100}) async {
    final owner = api.authenticatedUserId;
    if (owner == null) throw ApiException(401, '请先登录');
    final bounded = limit.clamp(1, 500);
    final raw = await _request('GET', _query('/timeline', {'limit': '$bounded'}));
    final rows = v2List(raw, '记忆列表', bounded)
        .map((item) => V2MemoryPickerItem.parse(item, ownerId: owner))
        .where((item) => item.sourceType != 'AI_INFERENCE')
        .toList(growable: false);
    final ids = <String>{};
    for (final row in rows) {
      if (!ids.add(row.id.toLowerCase())) return v2Invalid('记忆列表');
    }
    return List.unmodifiable(rows);
  }

  Future<List<V2PlacePickerItem>> listPlaceChoices({int limit = 100}) async {
    final bounded = limit.clamp(1, 500);
    final raw = await _request(
      'GET',
      _query('/location/places', {'limit': '$bounded'}),
    );
    final rows = v2List(raw, '地点列表', bounded)
        .map(V2PlacePickerItem.parse)
        .toList(growable: false);
    final ids = <String>{};
    for (final row in rows) {
      if (!ids.add(row.id.toLowerCase())) return v2Invalid('地点列表');
    }
    return List.unmodifiable(rows);
  }

  Future<List<V2PersonMemoryTimelineRow>> listPersonMemories(
    String personId, {
    int limit = 50,
  }) async {
    final id = v2PathId(personId, '人物');
    final bounded = limit.clamp(1, 100);
    final raw = await _request(
      'GET',
      _query('/people/' + id + '/memories', {'limit': '$bounded'}),
    );
    final rows = v2List(raw, '人物记忆', bounded)
        .map((item) => V2PersonMemoryTimelineRow.parse(
              item,
              personId: personId,
            ))
        .toList(growable: false);
    final ids = <String>{};
    for (final row in rows) {
      if (!ids.add(row.link.id.toLowerCase())) return v2Invalid('人物记忆');
    }
    return List.unmodifiable(rows);
  }

  Future<V2PersonMemoryLink> linkPersonMemory({
    required String personId,
    required String memoryId,
    required String relationKind,
  }) async {
    final person = v2PathId(personId, '人物');
    final memory = v2PathId(memoryId, '记忆');
    final kind = v2Enum(
      relationKind,
      personMemoryRelationKinds,
      '人物记忆关系',
    );
    final raw = await _request(
      'POST',
      '/people/' + person + '/memories/' + memory,
      body: {'relation_kind': kind},
    );
    return V2PersonMemoryLink.parse(
      raw,
      expectedPersonId: personId,
      expectedMemoryId: memoryId,
    );
  }

  Future<V2PersonMemoryLink> updatePersonMemory({
    required V2PersonMemoryLink link,
    required String relationKind,
  }) async {
    final person = v2PathId(link.personId, '人物');
    final memory = v2PathId(link.memoryId, '记忆');
    final kind = v2Enum(
      relationKind,
      personMemoryRelationKinds,
      '人物记忆关系',
    );
    final raw = await _request(
      'PATCH',
      '/people/' + person + '/memories/' + memory,
      body: {
        'relation_kind': kind,
        'expected_revision': link.revision,
      },
    );
    return V2PersonMemoryLink.parse(
      raw,
      expectedPersonId: link.personId,
      expectedMemoryId: link.memoryId,
    );
  }

  Future<void> unlinkPersonMemory({
    required String personId,
    required String memoryId,
  }) async {
    await _request(
      'DELETE',
      '/people/' +
          v2PathId(personId, '人物') +
          '/memories/' +
          v2PathId(memoryId, '记忆'),
    );
  }

  Future<List<V2PersonInteraction>> listRecentInteractions({
    int limit = 50,
  }) async {
    final bounded = limit.clamp(1, 100);
    final raw = await _request(
      'GET',
      _query('/people/interactions', {'limit': '$bounded'}),
    );
    return List.unmodifiable(
      v2List(raw, '人物互动', bounded).map(V2PersonInteraction.parse),
    );
  }

  Future<List<V2RelationshipProjection>> listRelationships(
    String personId, {
    int limit = 50,
  }) async {
    final id = v2PathId(personId, '人物');
    final bounded = limit.clamp(1, 100);
    final raw = await _request(
      'GET',
      _query('/people/' + id + '/relationships', {'limit': '$bounded'}),
    );
    return parseRelationshipProjectionList(
      raw,
      personId: personId,
      limit: bounded,
    );
  }

  Future<V2Relationship> createRelationship({
    required String personAId,
    required String personBId,
    required String kind,
    String? customLabel,
    String? note,
  }) async {
    if (personAId.toLowerCase() == personBId.toLowerCase()) {
      throw ArgumentError('不能把人物与自己建立关系');
    }
    final normalizedKind = v2Enum(kind, relationshipKinds, '人物关系');
    final custom = customLabel?.trim();
    if (normalizedKind == 'OTHER'
        ? (custom == null || custom.isEmpty)
        : (custom != null && custom.isNotEmpty)) {
      throw ArgumentError('人物关系类型与自定义标签不一致');
    }
    final raw = await _request('POST', '/people/relationships', body: {
      'person_a_id': v2Uuid(personAId, '人物关系'),
      'person_b_id': v2Uuid(personBId, '人物关系'),
      'relationship_kind': normalizedKind,
      'custom_label': normalizedKind == 'OTHER' ? custom : null,
      'note': note?.trim().isEmpty == true ? null : note?.trim(),
    });
    return V2Relationship.parse(
      raw,
      personAId: personAId,
      personBId: personBId,
    );
  }

  Future<V2Relationship> updateRelationship(
    V2Relationship relationship, {
    required String kind,
    String? customLabel,
    String? note,
  }) async {
    final normalizedKind = v2Enum(kind, relationshipKinds, '人物关系');
    final custom = customLabel?.trim();
    if (normalizedKind == 'OTHER'
        ? (custom == null || custom.isEmpty)
        : (custom != null && custom.isNotEmpty)) {
      throw ArgumentError('人物关系类型与自定义标签不一致');
    }
    final raw = await _request(
      'PATCH',
      '/people/relationships/' + v2PathId(relationship.id, '人物关系'),
      body: {
        'expected_revision': relationship.revision,
        'relationship_kind': normalizedKind,
        'custom_label': normalizedKind == 'OTHER' ? custom : null,
        'note': note?.trim().isEmpty == true ? null : note?.trim(),
      },
    );
    return V2Relationship.parse(raw, expectedId: relationship.id);
  }

  Future<void> deleteRelationship(String relationshipId) async {
    await _request(
      'DELETE',
      '/people/relationships/' + v2PathId(relationshipId, '人物关系'),
    );
  }

  Future<V2KnownDuration> getKnownDuration(String personId) async {
    final raw = await _request(
      'GET',
      '/people/' + v2PathId(personId, '人物') + '/known-duration',
    );
    return V2KnownDuration.parse(raw, personId: personId);
  }

  Future<V2GraphNeighborhood> graphNeighborhood({
    required String kind,
    required String entityId,
    int limit = 50,
  }) async {
    final normalizedKind = v2Enum(kind, graphNodeKinds, '关系图谱');
    final bounded = limit.clamp(1, 100);
    final raw = await _request(
      'GET',
      _query(
        '/graph/neighborhood/' +
            normalizedKind +
            '/' +
            v2PathId(entityId, '图谱实体'),
        {'limit': '$bounded'},
      ),
    );
    return V2GraphNeighborhood.parse(
      raw,
      expectedKind: normalizedKind,
      expectedId: entityId,
    );
  }

  Future<List<V2LifeEvent>> listLifeEvents({int limit = 50}) async {
    final bounded = limit.clamp(1, 100);
    final raw = await _request(
      'GET',
      _query('/life-events', {'limit': '$bounded'}),
    );
    return parseLifeEventList(raw, limit: bounded);
  }

  Future<V2LifeEvent> createLifeEvent({
    required String kind,
    required String title,
    String? customLabel,
    String? note,
    required String startedAt,
    String? endedAt,
    String? placeId,
  }) async {
    final normalizedKind = v2Enum(kind, lifeEventKinds, '人生事件');
    final raw = await _request('POST', '/life-events', body: {
      'event_kind': normalizedKind,
      'title': title.trim(),
      'custom_label': normalizedKind == 'OTHER' ? customLabel?.trim() : null,
      'note': note?.trim().isEmpty == true ? null : note?.trim(),
      'started_at': v2Aware(startedAt, '人生事件'),
      'ended_at': endedAt?.trim().isEmpty == true
          ? null
          : (endedAt == null ? null : v2Aware(endedAt, '人生事件')),
      'place_id': placeId?.trim().isEmpty == true
          ? null
          : (placeId == null ? null : v2Uuid(placeId, '人生事件')),
    });
    return V2LifeEvent.parse(raw);
  }

  Future<V2LifeEvent> updateLifeEvent(
    V2LifeEvent event, {
    required String kind,
    required String title,
    String? customLabel,
    String? note,
    required String startedAt,
    String? endedAt,
    String? placeId,
  }) async {
    final normalizedKind = v2Enum(kind, lifeEventKinds, '人生事件');
    final raw = await _request(
      'PATCH',
      '/life-events/' + v2PathId(event.id, '人生事件'),
      body: {
        'expected_revision': event.revision,
        'event_kind': normalizedKind,
        'title': title.trim(),
        'custom_label': normalizedKind == 'OTHER' ? customLabel?.trim() : null,
        'note': note?.trim().isEmpty == true ? null : note?.trim(),
        'started_at': v2Aware(startedAt, '人生事件'),
        'ended_at': endedAt?.trim().isEmpty == true
            ? null
            : (endedAt == null ? null : v2Aware(endedAt, '人生事件')),
        'place_id': placeId?.trim().isEmpty == true
            ? null
            : (placeId == null ? null : v2Uuid(placeId, '人生事件')),
      },
    );
    return V2LifeEvent.parse(raw, expectedId: event.id);
  }

  Future<void> deleteLifeEvent(String eventId) async {
    await _request('DELETE', '/life-events/' + v2PathId(eventId, '人生事件'));
  }

  Future<List<V2LifeEventMemoryEvidence>> listLifeEventMemories(
    String eventId, {
    int limit = 50,
  }) async {
    final bounded = limit.clamp(1, 100);
    final raw = await _request(
      'GET',
      _query(
        '/life-events/' + v2PathId(eventId, '人生事件') + '/memories',
        {'limit': '$bounded'},
      ),
    );
    final rows = v2List(raw, '事件证据', bounded)
        .map(V2LifeEventMemoryEvidence.parse)
        .toList(growable: false);
    final ids = <String>{};
    for (final row in rows) {
      if (!ids.add(row.linkId.toLowerCase())) return v2Invalid('事件证据');
    }
    return List.unmodifiable(rows);
  }

  Future<V2LifeEventMemoryEvidence> linkLifeEventMemory({
    required String eventId,
    required String memoryId,
  }) async {
    final raw = await _request(
      'POST',
      '/life-events/' +
          v2PathId(eventId, '人生事件') +
          '/memories/' +
          v2PathId(memoryId, '记忆'),
    );
    final parsed = V2LifeEventMemoryEvidence.parse(raw);
    if (parsed.memoryId.toLowerCase() != memoryId.toLowerCase()) {
      return v2Invalid('事件证据');
    }
    return parsed;
  }

  Future<void> unlinkLifeEventMemory({
    required String eventId,
    required String memoryId,
  }) async {
    await _request(
      'DELETE',
      '/life-events/' +
          v2PathId(eventId, '人生事件') +
          '/memories/' +
          v2PathId(memoryId, '记忆'),
    );
  }

  Future<List<V2LifeStage>> listLifeStages({int limit = 50}) async {
    final bounded = limit.clamp(1, 100);
    final raw = await _request(
      'GET',
      _query('/life-stages', {'limit': '$bounded'}),
    );
    return parseLifeStageList(raw, limit: bounded);
  }

  Future<V2LifeStage> createLifeStage({
    required String kind,
    required String title,
    String? customLabel,
    String? note,
    required String startedAt,
    String? endedAt,
  }) async {
    final normalizedKind = v2Enum(kind, lifeStageKinds, '人生阶段');
    final raw = await _request('POST', '/life-stages', body: {
      'stage_kind': normalizedKind,
      'title': title.trim(),
      'custom_label': normalizedKind == 'OTHER' ? customLabel?.trim() : null,
      'note': note?.trim().isEmpty == true ? null : note?.trim(),
      'started_at': v2Aware(startedAt, '人生阶段'),
      'ended_at': endedAt?.trim().isEmpty == true
          ? null
          : (endedAt == null ? null : v2Aware(endedAt, '人生阶段')),
    });
    return V2LifeStage.parse(raw);
  }

  Future<V2LifeStage> updateLifeStage(
    V2LifeStage stage, {
    required String kind,
    required String title,
    String? customLabel,
    String? note,
    required String startedAt,
    String? endedAt,
  }) async {
    final normalizedKind = v2Enum(kind, lifeStageKinds, '人生阶段');
    final raw = await _request(
      'PATCH',
      '/life-stages/' + v2PathId(stage.id, '人生阶段'),
      body: {
        'expected_revision': stage.revision,
        'stage_kind': normalizedKind,
        'title': title.trim(),
        'custom_label': normalizedKind == 'OTHER' ? customLabel?.trim() : null,
        'note': note?.trim().isEmpty == true ? null : note?.trim(),
        'started_at': v2Aware(startedAt, '人生阶段'),
        'ended_at': endedAt?.trim().isEmpty == true
            ? null
            : (endedAt == null ? null : v2Aware(endedAt, '人生阶段')),
      },
    );
    return V2LifeStage.parse(raw, expectedId: stage.id);
  }

  Future<void> deleteLifeStage(String stageId) async {
    await _request('DELETE', '/life-stages/' + v2PathId(stageId, '人生阶段'));
  }

  Future<List<V2LifeStageEvent>> listLifeStageEvents(
    String stageId, {
    int limit = 50,
  }) async {
    final bounded = limit.clamp(1, 100);
    final raw = await _request(
      'GET',
      _query(
        '/life-stages/' + v2PathId(stageId, '人生阶段') + '/events',
        {'limit': '$bounded'},
      ),
    );
    final rows = v2List(raw, '阶段事件', bounded)
        .map(V2LifeStageEvent.parse)
        .toList(growable: false);
    final ids = <String>{};
    for (final row in rows) {
      if (!ids.add(row.linkId.toLowerCase())) return v2Invalid('阶段事件');
    }
    return List.unmodifiable(rows);
  }

  Future<V2LifeStageEvent> linkLifeStageEvent({
    required String stageId,
    required String eventId,
  }) async {
    final raw = await _request(
      'POST',
      '/life-stages/' +
          v2PathId(stageId, '人生阶段') +
          '/events/' +
          v2PathId(eventId, '人生事件'),
    );
    final parsed = V2LifeStageEvent.parse(raw);
    if (parsed.lifeEventId.toLowerCase() != eventId.toLowerCase()) {
      return v2Invalid('阶段事件');
    }
    return parsed;
  }

  Future<void> unlinkLifeStageEvent({
    required String stageId,
    required String eventId,
  }) async {
    await _request(
      'DELETE',
      '/life-stages/' +
          v2PathId(stageId, '人生阶段') +
          '/events/' +
          v2PathId(eventId, '人生事件'),
    );
  }

  Future<V2LongTermReasoning> reasonAboutLifeStage({
    required String stageId,
    required String question,
  }) async {
    final normalized = question.trim();
    if (normalized.isEmpty || normalized.length > 2000) {
      throw ArgumentError('长期回顾问题需为 1–2000 个字符');
    }
    final raw = await _request(
      'POST',
      '/life-stages/' + v2PathId(stageId, '人生阶段') + '/reason',
      body: {'question': normalized},
    );
    return V2LongTermReasoning.parse(raw, stageId: stageId);
  }

  Future<V2LifeHistoryPage> getLifeHistory({
    required int startYear,
    required int endYear,
    int limit = 50,
    String? cursor,
  }) async {
    if (startYear < 1 || endYear > 9998 || startYear > endYear) {
      throw ArgumentError('年份范围无效');
    }
    final bounded = limit.clamp(1, 100);
    final query = <String, String>{
      'start_year': '$startYear',
      'end_year': '$endYear',
      'limit': '$bounded',
      if (cursor != null) 'cursor': v2Cursor(cursor, '多年时间线'),
    };
    final raw = await _request(
      'GET',
      _query('/life-history/timeline', query),
    );
    return V2LifeHistoryPage.parse(
      raw,
      startYear: startYear,
      endYear: endYear,
    );
  }

  Future<V2AnnualMemoir> generateAnnualMemoir(String year) async {
    final target = v2Year(year, '年度回忆录');
    final raw = await _request(
      'POST',
      '/memoirs/annual',
      body: {'target_year': target},
    );
    return V2AnnualMemoir.parse(raw, year: target);
  }

  Future<V2AnnualMemoirPhotoPage> getAnnualMemoirPhotos(
    String year, {
    int limit = 24,
    String? cursor,
  }) async {
    final target = v2Year(year, '年度照片');
    final bounded = limit.clamp(1, 50);
    final query = <String, String>{
      'limit': '$bounded',
      if (cursor != null) 'cursor': v2Cursor(cursor, '年度照片'),
    };
    final raw = await _request(
      'GET',
      _query('/memoirs/annual/' + target + '/photos', query),
    );
    return V2AnnualMemoirPhotoPage.parse(raw, year: target);
  }

  Future<V2SignedMediaDownload> getVerifiedMediaDownload(String mediaId) async {
    final id = v2PathId(mediaId, '媒体下载');
    final raw = await _request('POST', '/media/' + id + '/download');
    return V2SignedMediaDownload.parse(raw, mediaId: mediaId);
  }

  Future<V2LifeMemoirStagePage> getLifeMemoirStages({
    int limit = 50,
    String? cursor,
  }) async {
    final bounded = limit.clamp(1, 100);
    final query = <String, String>{
      'limit': '$bounded',
      if (cursor != null) 'cursor': v2Cursor(cursor, '人生回忆录阶段'),
    };
    final raw = await _request(
      'GET',
      _query('/memoirs/life/stages', query),
    );
    return V2LifeMemoirStagePage.parse(raw);
  }

  Future<V2LifeMemoirChapter> generateLifeMemoirChapter(String stageId) async {
    final id = v2PathId(stageId, '人生回忆录章节');
    final raw = await _request('POST', '/memoirs/life/stages/' + id);
    return V2LifeMemoirChapter.parse(raw, stageId: stageId);
  }
}
