enum AiPresentationState { explicit, inferred, uncertain, unavailable }

class AiPresentation {
  const AiPresentation({
    required this.state,
    required this.label,
    required this.detail,
  });

  final AiPresentationState state;
  final String label;
  final String detail;
}

const explicitAiPresentation = AiPresentation(
  state: AiPresentationState.explicit,
  label: '明确记录',
  detail: '这是你明确保存的记录。',
);

const inferredAiPresentation = AiPresentation(
  state: AiPresentationState.inferred,
  label: 'AI 整理',
  detail: '基于你的记录整理，你可以查看下方参考记录。',
);

const uncertainAiPresentation = AiPresentation(
  state: AiPresentationState.uncertain,
  label: '依据还不充分',
  detail: '现有记录还不足以整理出可靠结论。',
);

const unavailableAiPresentation = AiPresentation(
  state: AiPresentationState.unavailable,
  label: '暂时无法整理',
  detail: '这次没有整理成功，可以稍后再试。',
);

const _readySummaryStatuses = {
  'DAILY_SUMMARY_READY',
  'MONTHLY_SUMMARY_READY',
  'ANNUAL_SUMMARY_READY',
};

const _unavailableSummaryStatuses = {
  'NO_SUMMARIZABLE_EVIDENCE',
  'PROVIDER_FAILED',
  'MALFORMED_PROVIDER_OUTPUT',
  'INVALID_CITATION',
  'DATA_CHANGED_DURING_GENERATION',
};

AiPresentation summaryAiPresentation(String status) {
  if (_readySummaryStatuses.contains(status)) return inferredAiPresentation;
  if (status == 'SUMMARY_INCOMPLETE') return uncertainAiPresentation;
  return unavailableAiPresentation;
}

bool isKnownSummaryPresentationStatus(String status) =>
    _readySummaryStatuses.contains(status) ||
    status == 'SUMMARY_INCOMPLETE' ||
    _unavailableSummaryStatuses.contains(status);
