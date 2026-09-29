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
  detail: '这是明确保存的原始记录，不是 AI 生成的结论。',
);

const inferredAiPresentation = AiPresentation(
  state: AiPresentationState.inferred,
  label: 'AI 推断（有证据支持）',
  detail: '这是 AI 根据下方证据生成的回答，不等同于原始事实记录。',
);

const uncertainAiPresentation = AiPresentation(
  state: AiPresentationState.uncertain,
  label: 'AI 推断（证据不足）',
  detail: '当前证据不足以形成完整结论。',
);

const unavailableAiPresentation = AiPresentation(
  state: AiPresentationState.unavailable,
  label: '暂不可用',
  detail: '当前没有可安全展示的 AI 结论。',
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
