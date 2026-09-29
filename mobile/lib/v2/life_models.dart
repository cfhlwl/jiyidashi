import '../ai_inference_presentation.dart';
import 'people_models.dart';
import 'v2_common.dart';

const Set<String> lifeEventKinds = {
  'TRAVEL',
  'MEDICAL',
  'GATHERING',
  'WORK',
  'EDUCATION',
  'FAMILY',
  'OTHER',
};
const Set<String> lifeStageKinds = {
  'WORK',
  'EDUCATION',
  'FAMILY',
  'RESIDENCE',
  'TRAVEL',
  'OTHER',
};
const Set<String> reasoningStatuses = {
  'ANSWERED',
  'NO_ANSWERABLE_EVIDENCE',
  'EVIDENCE_INCOMPLETE',
  'PROVIDER_FAILED',
  'MALFORMED_PROVIDER_OUTPUT',
  'INVALID_CITATION',
  'EVIDENCE_CHANGED_DURING_GENERATION',
};
const Set<String> reasoningEvidenceKinds = {
  'LIFE_STAGE',
  'LIFE_EVENT',
  'MEMORY',
};

class V2LifeEvent {
  const V2LifeEvent({
    required this.id,
    required this.kind,
    required this.title,
    required this.customLabel,
    required this.note,
    required this.startedAt,
    required this.endedAt,
    required this.placeId,
    required this.revision,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String kind;
  final String title;
  final String? customLabel;
  final String? note;
  final String startedAt;
  final String? endedAt;
  final String? placeId;
  final int revision;
  final String createdAt;
  final String updatedAt;

  factory V2LifeEvent.parse(Object? value, {String? expectedId}) {
    final raw = v2Map(value, '人生事件');
    final kind = v2Enum(raw['event_kind'], lifeEventKinds, '人生事件');
    final custom = v2NullableText(
      raw['custom_label'],
      label: '人生事件',
      max: 120,
    );
    if (kind == 'OTHER'
        ? (custom == null || custom.trim().isEmpty)
        : custom != null) {
      return v2Invalid('人生事件');
    }
    final startedAt = v2Aware(raw['started_at'], '人生事件');
    final endedAt = v2NullableAware(raw['ended_at'], '人生事件');
    if (endedAt != null &&
        DateTime.parse(endedAt).isBefore(DateTime.parse(startedAt))) {
      return v2Invalid('人生事件');
    }
    final result = V2LifeEvent(
      id: v2Uuid(raw['id'], '人生事件'),
      kind: kind,
      title: v2Text(raw['title'], label: '人生事件', max: 240),
      customLabel: custom,
      note: v2NullableText(raw['note'], label: '人生事件', max: 5000),
      startedAt: startedAt,
      endedAt: endedAt,
      placeId: v2NullableUuid(raw['place_id'], '人生事件'),
      revision: v2Int(raw['revision'], label: '人生事件'),
      createdAt: v2Aware(raw['created_at'], '人生事件'),
      updatedAt: v2Aware(raw['updated_at'], '人生事件'),
    );
    if (expectedId != null &&
        result.id.toLowerCase() != expectedId.toLowerCase()) {
      return v2Invalid('人生事件');
    }
    return result;
  }
}

List<V2LifeEvent> parseLifeEventList(Object? value, {int limit = 100}) {
  final rows = v2List(value, '人生事件', limit)
      .map(V2LifeEvent.parse)
      .toList(growable: false);
  final ids = <String>{};
  for (final row in rows) {
    if (!ids.add(row.id.toLowerCase())) return v2Invalid('人生事件');
  }
  return List.unmodifiable(rows);
}

class V2LifeEventMemoryEvidence {
  const V2LifeEventMemoryEvidence({
    required this.linkId,
    required this.memoryId,
    required this.memoryType,
    required this.title,
    required this.content,
    required this.occurredAt,
    required this.sourceType,
    required this.createdAt,
  });

  final String linkId;
  final String memoryId;
  final String memoryType;
  final String? title;
  final String content;
  final String occurredAt;
  final String sourceType;
  final String createdAt;

  factory V2LifeEventMemoryEvidence.parse(Object? value) {
    final raw = v2Map(value, '事件证据');
    return V2LifeEventMemoryEvidence(
      linkId: v2Uuid(raw['link_id'], '事件证据'),
      memoryId: v2Uuid(raw['memory_id'], '事件证据'),
      memoryType: v2Enum(raw['memory_type'], memoryTypes, '事件证据'),
      title: v2NullableText(raw['title'], label: '事件证据', max: 240),
      content: v2Text(raw['content'], label: '事件证据', max: 20000),
      occurredAt: v2Aware(raw['occurred_at'], '事件证据'),
      sourceType: v2Enum(raw['source_type'], sourceTypes, '事件证据'),
      createdAt: v2Aware(raw['created_at'], '事件证据'),
    );
  }
}

class V2LifeStage {
  const V2LifeStage({
    required this.id,
    required this.kind,
    required this.title,
    required this.customLabel,
    required this.note,
    required this.startedAt,
    required this.endedAt,
    required this.revision,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String kind;
  final String title;
  final String? customLabel;
  final String? note;
  final String startedAt;
  final String? endedAt;
  final int revision;
  final String createdAt;
  final String updatedAt;

  factory V2LifeStage.parse(Object? value, {String? expectedId}) {
    final raw = v2Map(value, '人生阶段');
    final kind = v2Enum(raw['stage_kind'], lifeStageKinds, '人生阶段');
    final custom = v2NullableText(
      raw['custom_label'],
      label: '人生阶段',
      max: 120,
    );
    if (kind == 'OTHER'
        ? (custom == null || custom.trim().isEmpty)
        : custom != null) {
      return v2Invalid('人生阶段');
    }
    final startedAt = v2Aware(raw['started_at'], '人生阶段');
    final endedAt = v2NullableAware(raw['ended_at'], '人生阶段');
    if (endedAt != null &&
        DateTime.parse(endedAt).isBefore(DateTime.parse(startedAt))) {
      return v2Invalid('人生阶段');
    }
    final result = V2LifeStage(
      id: v2Uuid(raw['id'], '人生阶段'),
      kind: kind,
      title: v2Text(raw['title'], label: '人生阶段', max: 240),
      customLabel: custom,
      note: v2NullableText(raw['note'], label: '人生阶段', max: 5000),
      startedAt: startedAt,
      endedAt: endedAt,
      revision: v2Int(raw['revision'], label: '人生阶段'),
      createdAt: v2Aware(raw['created_at'], '人生阶段'),
      updatedAt: v2Aware(raw['updated_at'], '人生阶段'),
    );
    if (expectedId != null &&
        result.id.toLowerCase() != expectedId.toLowerCase()) {
      return v2Invalid('人生阶段');
    }
    return result;
  }
}

List<V2LifeStage> parseLifeStageList(Object? value, {int limit = 100}) {
  final rows = v2List(value, '人生阶段', limit)
      .map(V2LifeStage.parse)
      .toList(growable: false);
  final ids = <String>{};
  for (final row in rows) {
    if (!ids.add(row.id.toLowerCase())) return v2Invalid('人生阶段');
  }
  return List.unmodifiable(rows);
}

class V2LifeStageEvent {
  const V2LifeStageEvent({
    required this.linkId,
    required this.lifeEventId,
    required this.eventKind,
    required this.title,
    required this.customLabel,
    required this.note,
    required this.startedAt,
    required this.endedAt,
    required this.placeId,
    required this.createdAt,
  });

  final String linkId;
  final String lifeEventId;
  final String eventKind;
  final String title;
  final String? customLabel;
  final String? note;
  final String startedAt;
  final String? endedAt;
  final String? placeId;
  final String createdAt;

  factory V2LifeStageEvent.parse(Object? value) {
    final raw = v2Map(value, '阶段事件');
    final eventKind = v2Enum(raw['event_kind'], lifeEventKinds, '阶段事件');
    final customLabel = v2NullableText(
      raw['custom_label'],
      label: '阶段事件',
      max: 120,
    );
    if (eventKind == 'OTHER'
        ? customLabel == null
        : customLabel != null) {
      return v2Invalid('阶段事件');
    }
    final startedAt = v2Aware(raw['started_at'], '阶段事件');
    final endedAt = v2NullableAware(raw['ended_at'], '阶段事件');
    if (endedAt != null &&
        DateTime.parse(endedAt).isBefore(DateTime.parse(startedAt))) {
      return v2Invalid('阶段事件');
    }
    return V2LifeStageEvent(
      linkId: v2Uuid(raw['link_id'], '阶段事件'),
      lifeEventId: v2Uuid(raw['life_event_id'], '阶段事件'),
      eventKind: eventKind,
      title: v2Text(raw['title'], label: '阶段事件', max: 240),
      customLabel: customLabel,
      note: v2NullableText(raw['note'], label: '阶段事件', max: 5000),
      startedAt: startedAt,
      endedAt: endedAt,
      placeId: v2NullableUuid(raw['place_id'], '阶段事件'),
      createdAt: v2Aware(raw['created_at'], '阶段事件'),
    );
  }
}

class V2AiProvenance {
  const V2AiProvenance({
    required this.gatewayRequestId,
    required this.purpose,
    required this.providerRequestId,
    required this.provider,
    required this.model,
  });

  final String gatewayRequestId;
  final String purpose;
  final String? providerRequestId;
  final String provider;
  final String model;

  factory V2AiProvenance.parse(Object? value) {
    final raw = v2Map(value, 'AI 来源');
    return V2AiProvenance(
      gatewayRequestId: v2Text(
        raw['gateway_request_id'],
        label: 'AI 来源',
        max: 240,
      ),
      purpose: v2Text(raw['purpose'], label: 'AI 来源', max: 240),
      providerRequestId: v2NullableText(
        raw['provider_request_id'],
        label: 'AI 来源',
        max: 500,
      ),
      provider: v2Text(raw['provider'], label: 'AI 来源', max: 240),
      model: v2Text(raw['model'], label: 'AI 来源', max: 240),
    );
  }
}

class V2LongTermCitation {
  const V2LongTermCitation({
    required this.slot,
    required this.kind,
    required this.lifeStageId,
    required this.lifeEventId,
    required this.memoryId,
    required this.memorySourceId,
    required this.memoryTrustState,
  });

  final String slot;
  final String kind;
  final String? lifeStageId;
  final String? lifeEventId;
  final String? memoryId;
  final String? memorySourceId;
  final String? memoryTrustState;

  factory V2LongTermCitation.parse(Object? value) {
    final raw = v2Map(value, 'AI 引用');
    final kind = v2Enum(raw['kind'], reasoningEvidenceKinds, 'AI 引用');
    final result = V2LongTermCitation(
      slot: v2Text(raw['slot'], label: 'AI 引用', max: 120),
      kind: kind,
      lifeStageId: v2NullableUuid(raw['life_stage_id'], 'AI 引用'),
      lifeEventId: v2NullableUuid(raw['life_event_id'], 'AI 引用'),
      memoryId: v2NullableUuid(raw['memory_id'], 'AI 引用'),
      memorySourceId: v2NullableUuid(raw['memory_source_id'], 'AI 引用'),
      memoryTrustState: v2NullableCitationTrust(
        raw['memory_trust_state'],
        'AI 引用',
      ),
    );

    if (kind == 'LIFE_STAGE') {
      if (result.lifeStageId == null ||
          result.lifeEventId != null ||
          result.memoryId != null ||
          result.memorySourceId != null ||
          result.memoryTrustState != null) {
        return v2Invalid('AI 引用');
      }
    } else if (kind == 'LIFE_EVENT') {
      if (result.lifeStageId == null ||
          result.lifeEventId == null ||
          result.memoryId != null ||
          result.memorySourceId != null ||
          result.memoryTrustState != null) {
        return v2Invalid('AI 引用');
      }
    } else if (result.lifeStageId == null ||
        result.lifeEventId == null ||
        result.memoryId == null ||
        result.memorySourceId == null ||
        result.memoryTrustState == null) {
      return v2Invalid('AI 引用');
    }
    return result;
  }
}

class V2LongTermReasoning {
  const V2LongTermReasoning({
    required this.status,
    required this.answer,
    required this.citations,
    required this.providerErrorCode,
    required this.provenance,
  });

  final String status;
  final String? answer;
  final List<V2LongTermCitation> citations;
  final String? providerErrorCode;
  final V2AiProvenance? provenance;

  factory V2LongTermReasoning.parse(
    Object? value, {
    required String stageId,
  }) {
    final raw = v2Map(value, '长期推理');
    final status = v2Enum(raw['status'], reasoningStatuses, '长期推理');
    final citations = v2List(raw['citations'], '长期推理', 100)
        .map(V2LongTermCitation.parse)
        .toList(growable: false);
    v2UniqueSlots(citations.map((item) => item.slot), label: '长期推理');
    if (citations.any(
      (item) => item.lifeStageId?.toLowerCase() != stageId.toLowerCase(),
    )) {
      return v2Invalid('长期推理');
    }
    final answer = v2NullableText(
      raw['answer'],
      label: '长期推理',
      max: 20000,
    );
    final errorCode = v2NullableText(
      raw['provider_error_code'],
      label: '长期推理',
      max: 500,
    );
    final provenance = raw['ai_provenance'] == null
        ? null
        : V2AiProvenance.parse(raw['ai_provenance']);

    if (status == 'ANSWERED') {
      if (answer == null ||
          citations.isEmpty ||
          provenance == null ||
          errorCode != null) {
        return v2Invalid('长期推理');
      }
    } else if (answer != null || citations.isNotEmpty) {
      return v2Invalid('长期推理');
    }

    final provenanceRequired =
        status == 'MALFORMED_PROVIDER_OUTPUT' || status == 'INVALID_CITATION';
    final provenanceForbidden = status == 'NO_ANSWERABLE_EVIDENCE' ||
        status == 'EVIDENCE_INCOMPLETE' ||
        status == 'PROVIDER_FAILED';
    if ((provenanceRequired && provenance == null) ||
        (provenanceForbidden && provenance != null)) {
      return v2Invalid('长期推理');
    }

    if (status == 'PROVIDER_FAILED') {
      if (errorCode == null) return v2Invalid('长期推理');
    } else if (errorCode != null) {
      return v2Invalid('长期推理');
    }

    return V2LongTermReasoning(
      status: status,
      answer: answer,
      citations: List.unmodifiable(citations),
      providerErrorCode: errorCode,
      provenance: provenance,
    );
  }

  AiPresentation get presentation {
    if (status == 'ANSWERED') return inferredAiPresentation;
    if (status == 'EVIDENCE_INCOMPLETE') return uncertainAiPresentation;
    return unavailableAiPresentation;
  }
}

const Set<String> lifeHistoryKinds = {
  'LIFE_EVENT',
  'LIFE_STAGE_STARTED',
  'LIFE_STAGE_ENDED',
};

class V2LifeHistoryItem {
  const V2LifeHistoryItem({
    required this.kind,
    required this.occurredAt,
    required this.title,
    required this.customLabel,
    required this.lifeEventId,
    required this.eventKind,
    required this.eventEndedAt,
    required this.placeId,
    required this.lifeStageId,
    required this.stageKind,
  });

  final String kind;
  final String occurredAt;
  final String title;
  final String? customLabel;
  final String? lifeEventId;
  final String? eventKind;
  final String? eventEndedAt;
  final String? placeId;
  final String? lifeStageId;
  final String? stageKind;

  factory V2LifeHistoryItem.parse(Object? value) {
    final raw = v2Map(value, '多年时间线');
    final kind = v2Enum(raw['kind'], lifeHistoryKinds, '多年时间线');
    final result = V2LifeHistoryItem(
      kind: kind,
      occurredAt: v2Aware(raw['occurred_at'], '多年时间线'),
      title: v2Text(raw['title'], label: '多年时间线', max: 240),
      customLabel: v2NullableText(
        raw['custom_label'],
        label: '多年时间线',
        max: 120,
      ),
      lifeEventId: v2NullableUuid(raw['life_event_id'], '多年时间线'),
      eventKind: raw['event_kind'] == null
          ? null
          : v2Enum(raw['event_kind'], lifeEventKinds, '多年时间线'),
      eventEndedAt: v2NullableAware(raw['event_ended_at'], '多年时间线'),
      placeId: v2NullableUuid(raw['place_id'], '多年时间线'),
      lifeStageId: v2NullableUuid(raw['life_stage_id'], '多年时间线'),
      stageKind: raw['stage_kind'] == null
          ? null
          : v2Enum(raw['stage_kind'], lifeStageKinds, '多年时间线'),
    );
    if (kind == 'LIFE_EVENT') {
      if (result.lifeEventId == null ||
          result.eventKind == null ||
          result.lifeStageId != null ||
          result.stageKind != null) {
        return v2Invalid('多年时间线');
      }
      if (result.eventKind == 'OTHER'
          ? result.customLabel == null
          : result.customLabel != null) {
        return v2Invalid('多年时间线');
      }
      if (result.eventEndedAt != null &&
          DateTime.parse(result.eventEndedAt!)
              .isBefore(DateTime.parse(result.occurredAt))) {
        return v2Invalid('多年时间线');
      }
    } else {
      if (result.lifeStageId == null ||
          result.stageKind == null ||
          result.lifeEventId != null ||
          result.eventKind != null ||
          result.eventEndedAt != null ||
          result.placeId != null) {
        return v2Invalid('多年时间线');
      }
      if (result.stageKind == 'OTHER'
          ? result.customLabel == null
          : result.customLabel != null) {
        return v2Invalid('多年时间线');
      }
    }
    return result;
  }
}

class V2LifeHistoryPage {
  const V2LifeHistoryPage({
    required this.timezone,
    required this.startYear,
    required this.endYear,
    required this.asOf,
    required this.items,
    required this.nextCursor,
  });

  final String timezone;
  final int startYear;
  final int endYear;
  final String asOf;
  final List<V2LifeHistoryItem> items;
  final String? nextCursor;

  factory V2LifeHistoryPage.parse(
    Object? value, {
    required int startYear,
    required int endYear,
  }) {
    final raw = v2Map(value, '多年时间线');
    final result = V2LifeHistoryPage(
      timezone: v2Text(raw['timezone'], label: '多年时间线', max: 120),
      startYear: v2Int(
        raw['start_year'],
        label: '多年时间线',
        min: 1,
        max: 9998,
      ),
      endYear: v2Int(
        raw['end_year'],
        label: '多年时间线',
        min: 1,
        max: 9998,
      ),
      asOf: v2Aware(raw['as_of'], '多年时间线'),
      items: List.unmodifiable(
        v2List(raw['items'], '多年时间线', 100)
            .map(V2LifeHistoryItem.parse),
      ),
      nextCursor: v2NullableCursor(raw['next_cursor'], '多年时间线'),
    );
    if (result.startYear != startYear ||
        result.endYear != endYear ||
        result.startYear > result.endYear) {
      return v2Invalid('多年时间线');
    }
    return result;
  }
}
