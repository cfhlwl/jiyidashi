import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/ai_inference_presentation.dart';

void main() {
  Map<String, dynamic> evidenceQuery() => {
        'can_answer': true,
        'answer': '护照在书房。',
        'certainty': 'evidence',
        'evidence': [
          {'source_type': 'USER_TEXT'}
        ],
        'memory_ids': ['11111111-1111-4111-8111-111111111111'],
      };

  test('evidence-backed query maps to INFERRED', () {
    final presentation = queryAiPresentation(evidenceQuery());
    expect(presentation.state, AiPresentationState.inferred);
    expect(presentation.label, 'AI 推断（有证据支持）');
    expect(isCanonicalQueryTrustShape(evidenceQuery()), isTrue);
  });

  test('canonical no-evidence maps to UNAVAILABLE', () {
    final result = <String, dynamic>{
      'can_answer': false,
      'answer': null,
      'certainty': 'unknown',
      'evidence': <dynamic>[],
      'memory_ids': <dynamic>[],
    };
    expect(
      queryAiPresentation(result).state,
      AiPresentationState.unavailable,
    );
    expect(isCanonicalQueryTrustShape(result), isTrue);
  });

  test('unknown or contradictory certainty fails canonical shape', () {
    final confirmed = evidenceQuery()..['certainty'] = 'confirmed';
    final missingEvidence = evidenceQuery()..['evidence'] = <dynamic>[];
    final future = evidenceQuery()..['certainty'] = 'future-value';
    expect(isCanonicalQueryTrustShape(confirmed), isFalse);
    expect(isCanonicalQueryTrustShape(missingEvidence), isFalse);
    expect(isCanonicalQueryTrustShape(future), isFalse);
  });

  test('summary statuses preserve cross-client four-state parity', () {
    for (final status in [
      'DAILY_SUMMARY_READY',
      'MONTHLY_SUMMARY_READY',
      'ANNUAL_SUMMARY_READY',
    ]) {
      expect(summaryAiPresentation(status).state, AiPresentationState.inferred);
    }
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

  test('explicit record presentation is independent from AI answer state', () {
    expect(explicitAiPresentation.state, AiPresentationState.explicit);
    expect(explicitAiPresentation.label, '明确记录');
  });
}
