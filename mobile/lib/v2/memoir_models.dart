import '../ai_inference_presentation.dart';
import 'life_models.dart';
import 'v2_common.dart';

const Set<String> annualSummaryStatuses = {
  'ANNUAL_SUMMARY_READY',
  'NO_SUMMARIZABLE_EVIDENCE',
  'SUMMARY_INCOMPLETE',
  'PROVIDER_FAILED',
  'MALFORMED_PROVIDER_OUTPUT',
  'INVALID_CITATION',
  'DATA_CHANGED_DURING_GENERATION',
};

class V2AnnualMemoirCitation {
  const V2AnnualMemoirCitation({
    required this.slot,
    required this.kind,
    required this.memoryId,
    required this.visitId,
    required this.trustState,
  });

  final String slot;
  final String kind;
  final String? memoryId;
  final String? visitId;
  final String? trustState;

  factory V2AnnualMemoirCitation.parse(Object? value) {
    final raw = v2Map(value, '年度回忆录引用');
    final kind = v2Enum(raw['kind'], {'MEMORY', 'VISIT'}, '年度回忆录引用');
    final result = V2AnnualMemoirCitation(
      slot: v2Text(raw['slot'], label: '年度回忆录引用', max: 120),
      kind: kind,
      memoryId: v2NullableUuid(raw['memory_id'], '年度回忆录引用'),
      visitId: v2NullableUuid(raw['visit_id'], '年度回忆录引用'),
      trustState: v2NullableCitationTrust(
        raw['trust_state'],
        '年度回忆录引用',
      ),
    );
    if (kind == 'MEMORY') {
      if (result.memoryId == null ||
          result.visitId != null ||
          result.trustState == null) {
        return v2Invalid('年度回忆录引用');
      }
    } else if (result.visitId == null ||
        result.memoryId != null ||
        result.trustState != null) {
      return v2Invalid('年度回忆录引用');
    }
    return result;
  }
}

class V2AnnualMemoirPhoto {
  const V2AnnualMemoirPhoto({
    required this.memoryId,
    required this.mediaId,
    required this.occurredAt,
    required this.title,
    required this.contentType,
  });

  final String memoryId;
  final String mediaId;
  final String occurredAt;
  final String? title;
  final String contentType;

  factory V2AnnualMemoirPhoto.parse(Object? value) {
    final raw = v2Map(value, '年度照片');
    return V2AnnualMemoirPhoto(
      memoryId: v2Uuid(raw['memory_id'], '年度照片'),
      mediaId: v2Uuid(raw['media_id'], '年度照片'),
      occurredAt: v2Aware(raw['occurred_at'], '年度照片'),
      title: v2NullableText(raw['title'], label: '年度照片', max: 240),
      contentType: v2Text(
        raw['content_type'],
        label: '年度照片',
        max: 120,
      ),
    );
  }
}

class V2AnnualMemoirPhotoPage {
  const V2AnnualMemoirPhotoPage({
    required this.timezone,
    required this.targetYear,
    required this.items,
    required this.nextCursor,
  });

  final String timezone;
  final String targetYear;
  final List<V2AnnualMemoirPhoto> items;
  final String? nextCursor;

  factory V2AnnualMemoirPhotoPage.parse(
    Object? value, {
    required String year,
  }) {
    final raw = v2Map(value, '年度照片');
    final result = V2AnnualMemoirPhotoPage(
      timezone: v2Text(raw['timezone'], label: '年度照片', max: 120),
      targetYear: v2Year(raw['target_year'], '年度照片'),
      items: List.unmodifiable(
        v2List(raw['items'], '年度照片', 50)
            .map(V2AnnualMemoirPhoto.parse),
      ),
      nextCursor: v2NullableCursor(raw['next_cursor'], '年度照片'),
    );
    if (result.targetYear != year) return v2Invalid('年度照片');
    return result;
  }
}

class V2SignedMediaDownload {
  const V2SignedMediaDownload({
    required this.mediaId,
    required this.method,
    required this.url,
    required this.headers,
    required this.expiresAt,
  });

  final String mediaId;
  final String method;
  final Uri url;
  final Map<String, String> headers;
  final String expiresAt;

  factory V2SignedMediaDownload.parse(
    Object? value, {
    required String mediaId,
  }) {
    final raw = v2Map(value, '媒体下载');
    final returnedId = v2Uuid(raw['media_id'], '媒体下载');
    if (returnedId.toLowerCase() != mediaId.toLowerCase()) {
      return v2Invalid('媒体下载');
    }
    final transfer = v2Map(raw['download'], '媒体下载');
    final method = v2Text(
      transfer['method'],
      label: '媒体下载',
      max: 16,
    ).toUpperCase();
    if (method != 'GET') return v2Invalid('媒体下载');
    final urlText = v2Text(
      transfer['url'],
      label: '媒体下载',
      max: 4096,
    );
    final url = Uri.tryParse(urlText);
    if (url == null || url.scheme != 'https') return v2Invalid('媒体下载');
    final rawHeaders = v2Map(transfer['headers'], '媒体下载');
    final headers = <String, String>{};
    for (final entry in rawHeaders.entries) {
      if (entry.value is! String ||
          entry.key.length > 200 ||
          (entry.value as String).length > 4000) {
        return v2Invalid('媒体下载');
      }
      headers[entry.key] = entry.value as String;
    }
    return V2SignedMediaDownload(
      mediaId: returnedId,
      method: method,
      url: url,
      headers: Map.unmodifiable(headers),
      expiresAt: v2Aware(transfer['expires_at'], '媒体下载'),
    );
  }
}

class V2AnnualMemoir {
  const V2AnnualMemoir({
    required this.status,
    required this.targetYear,
    required this.timezone,
    required this.narrativeStatus,
    required this.narrative,
    required this.citations,
    required this.timelineItems,
    required this.timelineNextCursor,
    required this.photoItems,
    required this.photoNextCursor,
  });

  final String status;
  final String targetYear;
  final String timezone;
  final String narrativeStatus;
  final String? narrative;
  final List<V2AnnualMemoirCitation> citations;
  final List<V2LifeHistoryItem> timelineItems;
  final String? timelineNextCursor;
  final List<V2AnnualMemoirPhoto> photoItems;
  final String? photoNextCursor;

  factory V2AnnualMemoir.parse(Object? value, {required String year}) {
    final raw = v2Map(value, '年度回忆录');
    final narrativeStatus = v2Enum(
      raw['narrative_status'],
      annualSummaryStatuses,
      '年度回忆录',
    );
    final narrative = v2NullableText(
      raw['narrative'],
      label: '年度回忆录',
      max: 30000,
    );
    final citations = v2List(
      raw['narrative_citations'],
      '年度回忆录',
      100,
    ).map(V2AnnualMemoirCitation.parse).toList(growable: false);
    v2UniqueSlots(
      citations.map((item) => item.slot),
      label: '年度回忆录',
    );
    if (narrativeStatus == 'ANNUAL_SUMMARY_READY') {
      if (narrative == null || citations.isEmpty) return v2Invalid('年度回忆录');
    } else if (narrative != null || citations.isNotEmpty) {
      return v2Invalid('年度回忆录');
    }

    final result = V2AnnualMemoir(
      status: v2Enum(
        raw['status'],
        {'MEMOIR_READY', 'MEMOIR_PARTIAL', 'MEMOIR_EMPTY'},
        '年度回忆录',
      ),
      targetYear: v2Year(raw['target_year'], '年度回忆录'),
      timezone: v2Text(raw['timezone'], label: '年度回忆录', max: 120),
      narrativeStatus: narrativeStatus,
      narrative: narrative,
      citations: List.unmodifiable(citations),
      timelineItems: List.unmodifiable(
        v2List(raw['timeline_items'], '年度回忆录', 100)
            .map(V2LifeHistoryItem.parse),
      ),
      timelineNextCursor: v2NullableCursor(
        raw['timeline_next_cursor'],
        '年度回忆录',
      ),
      photoItems: List.unmodifiable(
        v2List(raw['photo_items'], '年度回忆录', 50)
            .map(V2AnnualMemoirPhoto.parse),
      ),
      photoNextCursor: v2NullableCursor(
        raw['photo_next_cursor'],
        '年度回忆录',
      ),
    );
    if (result.targetYear != year) return v2Invalid('年度回忆录');

    final expectedStatus = narrativeStatus == 'ANNUAL_SUMMARY_READY'
        ? 'MEMOIR_READY'
        : narrativeStatus == 'NO_SUMMARIZABLE_EVIDENCE' &&
                result.timelineItems.isEmpty &&
                result.photoItems.isEmpty
            ? 'MEMOIR_EMPTY'
            : 'MEMOIR_PARTIAL';
    if (result.status != expectedStatus) return v2Invalid('年度回忆录');
    return result;
  }

  AiPresentation get presentation => summaryAiPresentation(narrativeStatus);
}

class V2LifeMemoirStage {
  const V2LifeMemoirStage({
    required this.lifeStageId,
    required this.stageKind,
    required this.title,
    required this.customLabel,
    required this.startedAt,
    required this.endedAt,
  });

  final String lifeStageId;
  final String stageKind;
  final String title;
  final String? customLabel;
  final String startedAt;
  final String? endedAt;

  factory V2LifeMemoirStage.parse(Object? value) {
    final raw = v2Map(value, '人生回忆录阶段');
    return V2LifeMemoirStage(
      lifeStageId: v2Uuid(raw['life_stage_id'], '人生回忆录阶段'),
      stageKind: v2Enum(raw['stage_kind'], lifeStageKinds, '人生回忆录阶段'),
      title: v2Text(raw['title'], label: '人生回忆录阶段', max: 240),
      customLabel: v2NullableText(
        raw['custom_label'],
        label: '人生回忆录阶段',
        max: 120,
      ),
      startedAt: v2Aware(raw['started_at'], '人生回忆录阶段'),
      endedAt: v2NullableAware(raw['ended_at'], '人生回忆录阶段'),
    );
  }
}

class V2LifeMemoirStagePage {
  const V2LifeMemoirStagePage({
    required this.items,
    required this.nextCursor,
  });

  final List<V2LifeMemoirStage> items;
  final String? nextCursor;

  factory V2LifeMemoirStagePage.parse(Object? value) {
    final raw = v2Map(value, '人生回忆录阶段');
    final items = v2List(raw['items'], '人生回忆录阶段', 100)
        .map(V2LifeMemoirStage.parse)
        .toList(growable: false);
    final ids = <String>{};
    for (final item in items) {
      if (!ids.add(item.lifeStageId.toLowerCase())) {
        return v2Invalid('人生回忆录阶段');
      }
    }
    return V2LifeMemoirStagePage(
      items: List.unmodifiable(items),
      nextCursor: v2NullableCursor(raw['next_cursor'], '人生回忆录阶段'),
    );
  }
}

class V2LifeMemoirChapter {
  const V2LifeMemoirChapter({
    required this.status,
    required this.lifeStageId,
    required this.reasoningStatus,
    required this.narrative,
    required this.citations,
  });

  final String status;
  final String lifeStageId;
  final String reasoningStatus;
  final String? narrative;
  final List<V2LongTermCitation> citations;

  factory V2LifeMemoirChapter.parse(
    Object? value, {
    required String stageId,
  }) {
    final raw = v2Map(value, '人生回忆录章节');
    final status = v2Enum(
      raw['status'],
      {'CHAPTER_READY', 'CHAPTER_EMPTY', 'CHAPTER_PARTIAL'},
      '人生回忆录章节',
    );
    final reasoningStatus = v2Enum(
      raw['reasoning_status'],
      reasoningStatuses,
      '人生回忆录章节',
    );
    final narrative = v2NullableText(
      raw['narrative'],
      label: '人生回忆录章节',
      max: 30000,
    );
    final citations = v2List(raw['citations'], '人生回忆录章节', 100)
        .map(V2LongTermCitation.parse)
        .toList(growable: false);
    v2UniqueSlots(
      citations.map((item) => item.slot),
      label: '人生回忆录章节',
    );
    final returnedStage = v2Uuid(raw['life_stage_id'], '人生回忆录章节');
    if (returnedStage.toLowerCase() != stageId.toLowerCase() ||
        citations.any(
          (item) => item.lifeStageId?.toLowerCase() != stageId.toLowerCase(),
        )) {
      return v2Invalid('人生回忆录章节');
    }

    if (reasoningStatus == 'ANSWERED') {
      if (status != 'CHAPTER_READY' ||
          narrative == null ||
          citations.isEmpty) {
        return v2Invalid('人生回忆录章节');
      }
    } else {
      if (narrative != null ||
          citations.isNotEmpty ||
          status == 'CHAPTER_READY') {
        return v2Invalid('人生回忆录章节');
      }
      if (reasoningStatus == 'NO_ANSWERABLE_EVIDENCE') {
        if (status != 'CHAPTER_EMPTY') return v2Invalid('人生回忆录章节');
      } else if (status != 'CHAPTER_PARTIAL') {
        return v2Invalid('人生回忆录章节');
      }
    }

    return V2LifeMemoirChapter(
      status: status,
      lifeStageId: returnedStage,
      reasoningStatus: reasoningStatus,
      narrative: narrative,
      citations: List.unmodifiable(citations),
    );
  }

  AiPresentation get presentation {
    if (reasoningStatus == 'ANSWERED') return inferredAiPresentation;
    if (reasoningStatus == 'EVIDENCE_INCOMPLETE') {
      return uncertainAiPresentation;
    }
    return unavailableAiPresentation;
  }
}
