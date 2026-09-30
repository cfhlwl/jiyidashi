import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/ai_inference_presentation.dart';

void main() {
  test('Trusted Summary READY maps to INFERRED', () {
    for (final status in [
      'DAILY_SUMMARY_READY',
      'MONTHLY_SUMMARY_READY',
      'ANNUAL_SUMMARY_READY',
    ]) {
      final presentation = summaryAiPresentation(status);
      expect(presentation.state, AiPresentationState.inferred);
      expect(presentation.label, 'AI 整理');
    }
  });

  test('summary incomplete and unavailable states stay fail closed', () {
    expect(
      summaryAiPresentation('SUMMARY_INCOMPLETE').state,
      AiPresentationState.uncertain,
    );
    for (final status in [
      'NO_SUMMARIZABLE_EVIDENCE',
      'PROVIDER_FAILED',
      'MALFORMED_PROVIDER_OUTPUT',
      'INVALID_CITATION',
      'DATA_CHANGED_DURING_GENERATION',
      'FUTURE_STATUS',
    ]) {
      expect(
        summaryAiPresentation(status).state,
        AiPresentationState.unavailable,
      );
    }
    expect(isKnownSummaryPresentationStatus('FUTURE_STATUS'), isFalse);
  });

  test('explicit record presentation remains independent from AI surfaces', () {
    expect(explicitAiPresentation.state, AiPresentationState.explicit);
    expect(explicitAiPresentation.label, '明确记录');
  });
}
