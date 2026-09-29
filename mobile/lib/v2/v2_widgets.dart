// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../ai_inference_presentation.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';

class V2TrustBadge extends StatelessWidget {
  const V2TrustBadge({
    super.key,
    required this.presentation,
  });

  final AiPresentation presentation;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = switch (presentation.state) {
      AiPresentationState.explicit => theme.colorScheme.secondaryContainer,
      AiPresentationState.inferred => theme.colorScheme.primaryContainer,
      AiPresentationState.uncertain => theme.colorScheme.tertiaryContainer,
      AiPresentationState.unavailable => theme.colorScheme.surfaceContainerHighest,
    };
    final foreground = switch (presentation.state) {
      AiPresentationState.explicit => theme.colorScheme.onSecondaryContainer,
      AiPresentationState.inferred => theme.colorScheme.onPrimaryContainer,
      AiPresentationState.uncertain => theme.colorScheme.onTertiaryContainer,
      AiPresentationState.unavailable => theme.colorScheme.onSurfaceVariant,
    };
    return Semantics(
      label: '可信状态：' + presentation.label + '。' + presentation.detail,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(JiYiRadius.control),
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: JiYiSpacing.sm,
            vertical: JiYiSpacing.xs,
          ),
          child: Text(
            presentation.label,
            style: theme.textTheme.labelLarge?.copyWith(
              color: foreground,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ),
    );
  }
}

class V2ErrorState extends StatelessWidget {
  const V2ErrorState({
    super.key,
    required this.message,
    required this.onRetry,
  });

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        JiYiStatusBanner(
          kind: JiYiStatusKind.error,
          title: '加载失败',
          message: message,
        ),
        const SizedBox(height: JiYiSpacing.sm),
        OutlinedButton(
          onPressed: onRetry,
          child: const Text('重试'),
        ),
      ],
    );
  }
}

class V2OfflineErrorState extends StatelessWidget {
  const V2OfflineErrorState({
    super.key,
    required this.onRetry,
  });

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return V2ErrorState(
      message: '当前网络不可用。V2 人物/人生操作不会写入离线权威数据，请联网后重试。',
      onRetry: onRetry,
    );
  }
}

class V2KeyValue extends StatelessWidget {
  const V2KeyValue({
    super.key,
    required this.label,
    required this.value,
  });

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: JiYiSpacing.xxs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 86,
            child: Text(
              label,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ),
          const SizedBox(width: JiYiSpacing.xs),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}
