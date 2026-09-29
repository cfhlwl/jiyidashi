import 'v2_common.dart';

const Set<String> personMemoryRelationKinds = {'RELATED', 'MET'};
const Set<String> relationshipKinds = {
  'FAMILY',
  'FRIEND',
  'COLLEAGUE',
  'CLASSMATE',
  'OTHER',
};
const Set<String> memoryTypes = {
  'NOTE',
  'VOICE',
  'PHOTO',
  'PLACE',
  'OBJECT_LOCATION',
  'REMINDER',
  'EVENT',
};
const Set<String> sourceTypes = {
  'USER_TEXT',
  'USER_VOICE',
  'USER_PHOTO',
  'GPS',
  'PHOTO_EXIF',
  'SYSTEM_PLACE',
  'AI_INFERENCE',
};

class V2Person {
  const V2Person({
    required this.id,
    required this.displayName,
    required this.relationshipLabel,
    required this.note,
    required this.aliases,
    required this.revision,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String displayName;
  final String? relationshipLabel;
  final String? note;
  final List<String> aliases;
  final int revision;
  final String createdAt;
  final String updatedAt;

  factory V2Person.parse(Object? value, {String? expectedId}) {
    final raw = v2Map(value, '人物');
    final result = V2Person(
      id: v2Uuid(raw['id'], '人物'),
      displayName: v2Text(raw['display_name'], label: '人物', max: 200),
      relationshipLabel: v2NullableText(
        raw['relationship_label'],
        label: '人物',
        max: 120,
      ),
      note: v2NullableText(raw['note'], label: '人物', max: 5000),
      aliases: v2StringList(
        raw['aliases'],
        label: '人物',
        maxItems: 100,
        maxText: 200,
      ),
      revision: v2Int(raw['revision'], label: '人物'),
      createdAt: v2Aware(raw['created_at'], '人物'),
      updatedAt: v2Aware(raw['updated_at'], '人物'),
    );
    if (expectedId != null &&
        result.id.toLowerCase() != expectedId.toLowerCase()) {
      return v2Invalid('人物');
    }
    return result;
  }
}

List<V2Person> parsePersonList(Object? value, {int limit = 100}) {
  final raw = v2List(value, '人物列表', limit);
  final rows = raw.map(V2Person.parse).toList(growable: false);
  final ids = <String>{};
  for (final row in rows) {
    if (!ids.add(row.id.toLowerCase())) return v2Invalid('人物列表');
  }
  return List.unmodifiable(rows);
}

class V2MemoryPickerItem {
  const V2MemoryPickerItem({
    required this.id,
    required this.ownerId,
    required this.memoryType,
    required this.title,
    required this.content,
    required this.occurredAt,
    required this.sourceType,
    required this.isConfirmed,
    required this.editRevision,
  });

  final String id;
  final String ownerId;
  final String memoryType;
  final String? title;
  final String content;
  final String occurredAt;
  final String sourceType;
  final bool isConfirmed;
  final int editRevision;

  factory V2MemoryPickerItem.parse(Object? value, {required String ownerId}) {
    final raw = v2Map(value, '记忆');
    final rowOwner = v2Uuid(raw['user_id'], '记忆');
    if (rowOwner.toLowerCase() != ownerId.toLowerCase()) {
      return v2Invalid('记忆');
    }
    return V2MemoryPickerItem(
      id: v2Uuid(raw['id'], '记忆'),
      ownerId: rowOwner,
      memoryType: v2Enum(raw['memory_type'], memoryTypes, '记忆'),
      title: v2NullableText(raw['title'], label: '记忆', max: 240),
      content: v2Text(raw['content'], label: '记忆', max: 20000),
      occurredAt: v2Aware(raw['occurred_at'], '记忆'),
      sourceType: v2Enum(raw['source_type'], sourceTypes, '记忆'),
      isConfirmed: v2Bool(raw['is_confirmed'], '记忆'),
      editRevision: v2Int(raw['edit_revision'], label: '记忆'),
    );
  }
}

class V2PlacePickerItem {
  const V2PlacePickerItem({required this.id, required this.name});
  final String id;
  final String name;

  factory V2PlacePickerItem.parse(Object? value) {
    final raw = v2Map(value, '地点');
    return V2PlacePickerItem(
      id: v2Uuid(raw['id'], '地点'),
      name: v2Text(raw['name'], label: '地点', max: 500),
    );
  }
}

class V2PersonMemoryLink {
  const V2PersonMemoryLink({
    required this.id,
    required this.personId,
    required this.memoryId,
    required this.relationKind,
    required this.revision,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String personId;
  final String memoryId;
  final String relationKind;
  final int revision;
  final String createdAt;
  final String updatedAt;

  factory V2PersonMemoryLink.parse(
    Object? value, {
    String? expectedPersonId,
    String? expectedMemoryId,
  }) {
    final raw = v2Map(value, '人物记忆关系');
    final result = V2PersonMemoryLink(
      id: v2Uuid(raw['id'], '人物记忆关系'),
      personId: v2Uuid(raw['person_id'], '人物记忆关系'),
      memoryId: v2Uuid(raw['memory_id'], '人物记忆关系'),
      relationKind: v2Enum(
        raw['relation_kind'],
        personMemoryRelationKinds,
        '人物记忆关系',
      ),
      revision: v2Int(raw['revision'], label: '人物记忆关系'),
      createdAt: v2Aware(raw['created_at'], '人物记忆关系'),
      updatedAt: v2Aware(raw['updated_at'], '人物记忆关系'),
    );
    if (expectedPersonId != null &&
        result.personId.toLowerCase() != expectedPersonId.toLowerCase()) {
      return v2Invalid('人物记忆关系');
    }
    if (expectedMemoryId != null &&
        result.memoryId.toLowerCase() != expectedMemoryId.toLowerCase()) {
      return v2Invalid('人物记忆关系');
    }
    return result;
  }
}

class V2PersonMemoryTimelineRow {
  const V2PersonMemoryTimelineRow({
    required this.link,
    required this.occurredAt,
    required this.memoryTitle,
    required this.memoryContent,
    required this.memoryType,
  });

  final V2PersonMemoryLink link;
  final String occurredAt;
  final String? memoryTitle;
  final String memoryContent;
  final String memoryType;

  factory V2PersonMemoryTimelineRow.parse(
    Object? value, {
    required String personId,
  }) {
    final raw = v2Map(value, '人物记忆');
    return V2PersonMemoryTimelineRow(
      link: V2PersonMemoryLink.parse(raw, expectedPersonId: personId),
      occurredAt: v2Aware(raw['occurred_at'], '人物记忆'),
      memoryTitle: v2NullableText(
        raw['memory_title'],
        label: '人物记忆',
        max: 240,
      ),
      memoryContent: v2Text(
        raw['memory_content'],
        label: '人物记忆',
        max: 20000,
      ),
      memoryType: v2Enum(raw['memory_type'], memoryTypes, '人物记忆'),
    );
  }
}

class V2PersonInteraction {
  const V2PersonInteraction({
    required this.link,
    required this.personDisplayName,
    required this.occurredAt,
  });

  final V2PersonMemoryLink link;
  final String personDisplayName;
  final String occurredAt;

  factory V2PersonInteraction.parse(Object? value) {
    final raw = v2Map(value, '人物互动');
    return V2PersonInteraction(
      link: V2PersonMemoryLink.parse(raw),
      personDisplayName: v2Text(
        raw['person_display_name'],
        label: '人物互动',
        max: 200,
      ),
      occurredAt: v2Aware(raw['occurred_at'], '人物互动'),
    );
  }
}

class V2Relationship {
  const V2Relationship({
    required this.id,
    required this.personAId,
    required this.personBId,
    required this.kind,
    required this.customLabel,
    required this.note,
    required this.revision,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String personAId;
  final String personBId;
  final String kind;
  final String? customLabel;
  final String? note;
  final int revision;
  final String createdAt;
  final String updatedAt;

  factory V2Relationship.parse(
    Object? value, {
    String? expectedId,
    String? personAId,
    String? personBId,
  }) {
    final raw = v2Map(value, '人物关系');
    final a = v2Uuid(raw['person_a_id'], '人物关系');
    final b = v2Uuid(raw['person_b_id'], '人物关系');
    if (a.toLowerCase() == b.toLowerCase()) return v2Invalid('人物关系');
    final kind = v2Enum(raw['relationship_kind'], relationshipKinds, '人物关系');
    final custom = v2NullableText(
      raw['custom_label'],
      label: '人物关系',
      max: 120,
    );
    if (kind == 'OTHER'
        ? (custom == null || custom.trim().isEmpty)
        : custom != null) {
      return v2Invalid('人物关系');
    }
    final result = V2Relationship(
      id: v2Uuid(raw['id'], '人物关系'),
      personAId: a,
      personBId: b,
      kind: kind,
      customLabel: custom,
      note: v2NullableText(raw['note'], label: '人物关系', max: 5000),
      revision: v2Int(raw['revision'], label: '人物关系'),
      createdAt: v2Aware(raw['created_at'], '人物关系'),
      updatedAt: v2Aware(raw['updated_at'], '人物关系'),
    );
    if (expectedId != null &&
        result.id.toLowerCase() != expectedId.toLowerCase()) {
      return v2Invalid('人物关系');
    }
    if (personAId != null || personBId != null) {
      if (personAId == null || personBId == null) return v2Invalid('人物关系');
      final expected = {personAId.toLowerCase(), personBId.toLowerCase()};
      final actual = {a.toLowerCase(), b.toLowerCase()};
      if (expected.length != 2 ||
          actual.length != 2 ||
          !expected.containsAll(actual)) {
        return v2Invalid('人物关系');
      }
    }
    return result;
  }
}

class V2RelationshipProjection {
  const V2RelationshipProjection({
    required this.relationshipId,
    required this.kind,
    required this.customLabel,
    required this.note,
    required this.revision,
    required this.otherPersonId,
    required this.otherPersonName,
    required this.createdAt,
    required this.updatedAt,
  });

  final String relationshipId;
  final String kind;
  final String? customLabel;
  final String? note;
  final int revision;
  final String otherPersonId;
  final String otherPersonName;
  final String createdAt;
  final String updatedAt;

  factory V2RelationshipProjection.parse(
    Object? value, {
    required String requestedPersonId,
  }) {
    final raw = v2Map(value, '人物关系');
    final other = v2Map(raw['other_person'], '人物关系');
    final otherId = v2Uuid(other['id'], '人物关系');
    if (otherId.toLowerCase() == requestedPersonId.toLowerCase()) {
      return v2Invalid('人物关系');
    }
    final kind = v2Enum(raw['relationship_kind'], relationshipKinds, '人物关系');
    final custom = v2NullableText(
      raw['custom_label'],
      label: '人物关系',
      max: 120,
    );
    if (kind == 'OTHER'
        ? (custom == null || custom.trim().isEmpty)
        : custom != null) {
      return v2Invalid('人物关系');
    }
    return V2RelationshipProjection(
      relationshipId: v2Uuid(raw['relationship_id'], '人物关系'),
      kind: kind,
      customLabel: custom,
      note: v2NullableText(raw['note'], label: '人物关系', max: 5000),
      revision: v2Int(raw['revision'], label: '人物关系'),
      otherPersonId: otherId,
      otherPersonName: v2Text(
        other['display_name'],
        label: '人物关系',
        max: 200,
      ),
      createdAt: v2Aware(raw['created_at'], '人物关系'),
      updatedAt: v2Aware(raw['updated_at'], '人物关系'),
    );
  }
}

class V2KnownDurationEvidence {
  const V2KnownDurationEvidence({
    required this.linkId,
    required this.memoryId,
    required this.memorySourceId,
    required this.relationKind,
    required this.trustState,
    required this.occurredAt,
  });

  final String linkId;
  final String memoryId;
  final String memorySourceId;
  final String relationKind;
  final String trustState;
  final String occurredAt;

  factory V2KnownDurationEvidence.parse(Object? value) {
    final raw = v2Map(value, '认识时长证据');
    return V2KnownDurationEvidence(
      linkId: v2Uuid(raw['person_memory_link_id'], '认识时长证据'),
      memoryId: v2Uuid(raw['memory_id'], '认识时长证据'),
      memorySourceId: v2Uuid(raw['memory_source_id'], '认识时长证据'),
      relationKind: v2Enum(
        raw['relation_kind'],
        personMemoryRelationKinds,
        '认识时长证据',
      ),
      trustState: v2CitationTrust(raw['trust_state'], '认识时长证据'),
      occurredAt: v2Aware(raw['occurred_at'], '认识时长证据'),
    );
  }
}

class V2KnownDuration {
  const V2KnownDuration({
    required this.status,
    required this.personId,
    required this.displayName,
    required this.asOf,
    required this.atLeastSinceAt,
    required this.elapsedDays,
    required this.earliestRelatedAt,
    required this.evidence,
  });

  final String status;
  final String personId;
  final String displayName;
  final String asOf;
  final String? atLeastSinceAt;
  final int? elapsedDays;
  final String? earliestRelatedAt;
  final V2KnownDurationEvidence? evidence;

  factory V2KnownDuration.parse(Object? value, {required String personId}) {
    final raw = v2Map(value, '认识时长');
    final status = v2Enum(
      raw['status'],
      {
        'KNOWN_SINCE_MET',
        'RELATED_EVIDENCE_ONLY',
        'NO_TRUSTED_EVIDENCE',
        'EVIDENCE_INCOMPLETE',
      },
      '认识时长',
    );
    final evidence = raw['evidence'] == null
        ? null
        : V2KnownDurationEvidence.parse(raw['evidence']);
    final result = V2KnownDuration(
      status: status,
      personId: v2Uuid(raw['person_id'], '认识时长'),
      displayName: v2Text(raw['display_name'], label: '认识时长', max: 200),
      asOf: v2Aware(raw['as_of'], '认识时长'),
      atLeastSinceAt: v2NullableAware(raw['at_least_since_at'], '认识时长'),
      elapsedDays: v2NullableInt(raw['elapsed_days'], label: '认识时长'),
      earliestRelatedAt: v2NullableAware(
        raw['earliest_related_at'],
        '认识时长',
      ),
      evidence: evidence,
    );
    if (result.personId.toLowerCase() != personId.toLowerCase()) {
      return v2Invalid('认识时长');
    }
    if (status == 'KNOWN_SINCE_MET') {
      if (result.atLeastSinceAt == null ||
          result.elapsedDays == null ||
          result.earliestRelatedAt != null ||
          evidence == null ||
          evidence.relationKind != 'MET' ||
          !v2SameInstant(result.atLeastSinceAt!, evidence.occurredAt)) {
        return v2Invalid('认识时长');
      }
    } else if (status == 'RELATED_EVIDENCE_ONLY') {
      if (result.atLeastSinceAt != null ||
          result.elapsedDays != null ||
          result.earliestRelatedAt == null ||
          evidence == null ||
          evidence.relationKind != 'RELATED' ||
          !v2SameInstant(result.earliestRelatedAt!, evidence.occurredAt)) {
        return v2Invalid('认识时长');
      }
    } else if (result.atLeastSinceAt != null ||
        result.elapsedDays != null ||
        result.earliestRelatedAt != null ||
        evidence != null) {
      return v2Invalid('认识时长');
    }
    return result;
  }
}

List<V2RelationshipProjection> parseRelationshipProjectionList(
  Object? value, {
  required String personId,
  int limit = 100,
}) {
  final raw = v2List(value, '人物关系列表', limit);
  final rows = raw
      .map((item) => V2RelationshipProjection.parse(
            item,
            requestedPersonId: personId,
          ))
      .toList(growable: false);
  final ids = <String>{};
  for (final row in rows) {
    if (!ids.add(row.relationshipId.toLowerCase())) {
      return v2Invalid('人物关系列表');
    }
  }
  return List.unmodifiable(rows);
}
