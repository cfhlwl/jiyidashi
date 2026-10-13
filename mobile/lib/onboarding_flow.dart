import 'package:flutter/material.dart';

import 'onboarding_state.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';

// [人工注释][S1-026] 引导 UI 只解释用户马上会执行的真实能力，并明确不申请后台定位/Stage 2 权限。

class OnboardingExperience extends StatelessWidget {
  const OnboardingExperience({
    super.key,
    required this.step,
    required this.child,
    required this.onStart,
    required this.onSkip,
    required this.onComplete,
    this.onPermissionsNext,
    this.permissionsPanel,
    this.onEnableNotifications,
    this.onImportPhotos,
  });

  final OnboardingStep? step;
  final Widget child;
  final VoidCallback onStart;
  final VoidCallback onSkip;
  final VoidCallback onComplete;
  final VoidCallback? onPermissionsNext;
  final Widget? permissionsPanel;
  final VoidCallback? onEnableNotifications;
  final VoidCallback? onImportPhotos;

  @override
  Widget build(BuildContext context) {
    final current = step;
    if (current == OnboardingStep.intro) {
      return OnboardingIntroPage(onStart: onStart, onSkip: onSkip);
    }
    if (current == OnboardingStep.permissions) {
      return OnboardingPermissionsPage(
        permissionsPanel: permissionsPanel,
        onContinue: onPermissionsNext ?? onStart,
        onEnableNotifications: onEnableNotifications,
        onImportPhotos: onImportPhotos,
        onSkip: onSkip,
      );
    }

    // [人工注释][S1-026] 完成/跳过引导时保持产品页始终位于 Column 的第二个槽位。
    // 这样 Flutter 会复用真实 Capture/Query State，用户刚看到的 Evidence 不会因去掉 GuideBar 被重建清空。
    return Column(
      children: [
        if (current == null)
          const SizedBox.shrink()
        else
          OnboardingGuideBar(
            step: current,
            onSkip: onSkip,
            onComplete: onComplete,
          ),
        Expanded(child: child),
      ],
    );
  }
}

// The intro does not request OS permissions. Each capability has a separate
// opt-in action on the next step; first login alone never starts collection.
class OnboardingIntroPage extends StatelessWidget {
  const OnboardingIntroPage({
    super.key,
    required this.onStart,
    required this.onSkip,
  });

  final VoidCallback onStart;
  final VoidCallback onSkip;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListView(
      key: const ValueKey('onboarding-intro'),
      padding: const EdgeInsets.fromLTRB(
        JiYiSpacing.lg,
        JiYiSpacing.lg,
        JiYiSpacing.lg,
        JiYiSpacing.xxl,
      ),
      children: [
        Semantics(
          header: true,
          child: Text(
            '用 3 分钟体验一次“记住并找回”',
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        const SizedBox(height: JiYiSpacing.xs),
        Text(
          '迹忆的重点不是替你猜，而是把你主动留下的内容保存下来，需要时再连同依据一起找回来。',
          style: theme.textTheme.bodyLarge?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: JiYiSpacing.lg),
        JiYiSectionCard(
          leading: Icon(
            Icons.route_outlined,
            color: theme.colorScheme.primary,
          ),
          title: '这次会做三件真实的事',
          child: const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _IntroItem(
                icon: Icons.bookmark_add_outlined,
                title: '1. 真的保存一条记忆',
                message: '直接使用“记一下”的正式保存流程，不创建演示数据。',
              ),
              SizedBox(height: JiYiSpacing.md),
              _IntroItem(
                icon: Icons.manage_search_outlined,
                title: '2. 从自己的记忆里找回来',
                message: '使用“问记忆”的正式查询入口。',
              ),
              SizedBox(height: JiYiSpacing.md),
              _IntroItem(
                icon: Icons.fact_check_outlined,
                title: '3. 看清回答为什么可信',
                message: '查看这次回答实际使用的来源和时间。',
              ),
            ],
          ),
        ),
        const SizedBox(height: JiYiSpacing.md),
        const JiYiStatusBanner(
          kind: JiYiStatusKind.info,
          title: '隐私说明',
          message: '这一步只处理你主动提交的内容，不会申请后台定位，也不会开启自动位置采集。',
        ),
        const SizedBox(height: JiYiSpacing.lg),
        FilledButton.icon(
          key: const ValueKey('onboarding-start'),
          onPressed: onStart,
          icon: const Icon(Icons.play_arrow_rounded),
          label: const Text('开始体验'),
        ),
        const SizedBox(height: JiYiSpacing.xs),
        TextButton(
          key: const ValueKey('onboarding-skip-intro'),
          onPressed: onSkip,
          child: const Text('暂时跳过'),
        ),
      ],
    );
  }
}

// Permission actions are explicit, and the native section continues to enforce
// server Privacy authority. This screen does not fabricate authorization states.
class OnboardingPermissionsPage extends StatelessWidget {
  const OnboardingPermissionsPage({
    super.key,
    this.permissionsPanel,
    this.onEnableNotifications,
    this.onImportPhotos,
    required this.onContinue,
    required this.onSkip,
  });

  final Widget? permissionsPanel;
  final VoidCallback? onEnableNotifications;
  final VoidCallback? onImportPhotos;
  final VoidCallback onContinue;
  final VoidCallback onSkip;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListView(
      key: const ValueKey('onboarding-permissions'),
      padding: const EdgeInsets.all(JiYiSpacing.lg),
      children: [
        Text('选择你希望开启的能力', style: theme.textTheme.headlineSmall),
        const SizedBox(height: JiYiSpacing.sm),
        Text(
          '所有权限都由你决定。拒绝或稍后开启也能正常使用迹忆；这里只展示系统实际授权与采集状态。',
          style: theme.textTheme.bodyMedium,
        ),
        const SizedBox(height: JiYiSpacing.lg),
        if (permissionsPanel != null) permissionsPanel!,
        const SizedBox(height: JiYiSpacing.md),
        JiYiSectionCard(
          leading: Icon(Icons.photo_library_outlined, color: theme.colorScheme.primary),
          title: '导入已有照片',
          subtitle: '只处理你稍后通过系统照片选择器主动选中的图片，不要求整机相册权限。',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('导入完全可选；只在你明确选择并再次确认后上传。'),
              const SizedBox(height: JiYiSpacing.sm),
              OutlinedButton.icon(
                key: const ValueKey('onboarding-import-photos'),
                onPressed: onImportPhotos,
                icon: const Icon(Icons.add_photo_alternate_outlined),
                label: const Text('选择已有照片导入'),
              ),
            ],
          ),
        ),
        const SizedBox(height: JiYiSpacing.md),
        JiYiSectionCard(
          leading: Icon(Icons.notifications_outlined, color: theme.colorScheme.primary),
          title: '通知（可选）',
          subtitle: '用于提醒与完成状态。只有点击下方按钮才申请系统通知权限。',
          child: Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton(
              key: const ValueKey('onboarding-enable-notifications'),
              onPressed: onEnableNotifications,
              child: const Text('允许通知'),
            ),
          ),
        ),
        const SizedBox(height: JiYiSpacing.lg),
        FilledButton(
          key: const ValueKey('onboarding-permissions-next'),
          onPressed: onContinue,
          child: const Text('继续真实记忆体验'),
        ),
        TextButton(
          key: const ValueKey('onboarding-permissions-skip'),
          onPressed: onSkip,
          child: const Text('暂时跳过引导'),
        ),
      ],
    );
  }
}

class _IntroItem extends StatelessWidget {
  const _IntroItem({
    required this.icon,
    required this.title,
    required this.message,
  });

  final IconData icon;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, color: theme.colorScheme.primary),
        const SizedBox(width: JiYiSpacing.sm),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: theme.textTheme.titleSmall),
              const SizedBox(height: JiYiSpacing.xs),
              Text(
                message,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class OnboardingGuideBar extends StatelessWidget {
  const OnboardingGuideBar({
    super.key,
    required this.step,
    required this.onSkip,
    required this.onComplete,
  });

  final OnboardingStep step;
  final VoidCallback onSkip;
  final VoidCallback onComplete;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final (progress, title, message) = switch (step) {
      OnboardingStep.capture => (
          1 / 3,
          '第 1 步 · 留下一条真实记忆',
          '在下面“写一句”里记录一件你稍后能认出来的事，然后点“帮我记住”。',
        ),
      OnboardingStep.retrieve => (
          2 / 3,
          '第 2 步 · 把刚才的记忆找回来',
          '刚才记录的正文已经带入查询。点击搜索框中的查询按钮，或使用键盘搜索，找回这条真实记录。',
        ),
      OnboardingStep.trust => (
          1.0,
          '第 3 步 · 看懂为什么可信',
          '打开“查看这次回答的依据”，确认这次回答实际使用的来源和时间，再完成引导。',
        ),
      OnboardingStep.intro || OnboardingStep.permissions =>
        throw StateError('Full-page onboarding steps have their own views'),
    };

    return Semantics(
      container: true,
      liveRegion: true,
      label: '$title。$message',
      child: Material(
        key: ValueKey<String>('onboarding-guide-${step.name}'),
        color: theme.colorScheme.primaryContainer,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(
            JiYiSpacing.lg,
            JiYiSpacing.sm,
            JiYiSpacing.sm,
            JiYiSpacing.sm,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              LinearProgressIndicator(
                value: progress,
                semanticsLabel: '新手引导进度',
                semanticsValue: '${(progress * 100).round()}%',
              ),
              const SizedBox(height: JiYiSpacing.sm),
              Text(
                title,
                style: theme.textTheme.titleSmall?.copyWith(
                  color: theme.colorScheme.onPrimaryContainer,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: JiYiSpacing.xs),
              Text(
                message,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onPrimaryContainer,
                ),
              ),
              const SizedBox(height: JiYiSpacing.xs),
              Row(
                children: [
                  TextButton(
                    key: const ValueKey('onboarding-skip'),
                    onPressed: onSkip,
                    child: const Text('跳过引导'),
                  ),
                  const Spacer(),
                  if (step == OnboardingStep.trust)
                    FilledButton.icon(
                      key: const ValueKey('onboarding-complete'),
                      onPressed: onComplete,
                      icon: const Icon(Icons.check_circle_outline),
                      label: const Text('完成引导'),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
