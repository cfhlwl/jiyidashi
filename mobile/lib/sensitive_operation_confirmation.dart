import 'package:flutter/material.dart';

import 'api_client.dart';
import 'ui/jiyi_tokens.dart';

enum SensitiveOperationStrength {
  disclosure,
  destructiveData,
  irreversibleAccount,
  permissionMutation,
  sensitiveLocation,
}

class SensitiveOperationSpec {
  const SensitiveOperationSpec({
    required this.id,
    required this.strength,
    required this.title,
    required this.summary,
    required this.scope,
    required this.undo,
    required this.confirmLabel,
    this.requiredPhrase,
    this.destructive = false,
  });

  const SensitiveOperationSpec.dataExport()
      : this(
          id: 'data-export',
          strength: SensitiveOperationStrength.disclosure,
          title: '导出这些数据？',
          summary: '将生成一份你当前账号可导出的个人数据文件。',
          scope: '仅包含本次请求明确列出的导出范围；导出不会修改服务器上的数据。',
          undo: '导出本身不会修改数据，但导出的文件需要由你自行安全保管。',
          confirmLabel: '导出这些数据',
        );

  const SensitiveOperationSpec.dataDelete()
      : this(
          id: 'data-delete',
          strength: SensitiveOperationStrength.destructiveData,
          title: '删除这些数据？',
          summary: '将删除当前账号中本次操作覆盖的数据。',
          scope: '实际删除范围以服务端当前权威状态为准，不会创建回收站或保留隐藏文件。',
          undo: '完成真实删除后无法通过迹忆恢复。',
          confirmLabel: '删除这些数据',
          destructive: true,
        );

  const SensitiveOperationSpec.accountDelete()
      : this(
          id: 'account-delete',
          strength: SensitiveOperationStrength.irreversibleAccount,
          title: '永久注销账号？',
          summary: '注销会永久删除账号身份、记忆、媒体、提醒和其他个人数据。',
          scope: '完成后原账号无法恢复；以后使用相同邮箱注册会得到一个全新的账号。',
          undo: '不可撤销。',
          confirmLabel: '永久注销',
          requiredPhrase: '注销账号',
          destructive: true,
        );

  const SensitiveOperationSpec.automaticLocationStart()
      : this(
          id: 'location-share',
          strength: SensitiveOperationStrength.sensitiveLocation,
          title: '开始自动位置记忆？',
          summary: '开启后，系统可在你授予的定位权限范围内记录位置，用于形成你的个人足迹。',
          scope: '只作用于当前迹忆账号；系统定位权限仍由操作系统单独控制。',
          undo: '可以随时关闭自动位置记忆；关闭不会补传暂停期间的位置。',
          confirmLabel: '开始位置记忆',
        );

  factory SensitiveOperationSpec.familyPermission({
    required bool enabled,
    required String permissionLabel,
    required String memberLabel,
  }) {
    return SensitiveOperationSpec(
      id: enabled ? 'family-grant' : 'family-revoke',
      strength: SensitiveOperationStrength.permissionMutation,
      title: enabled ? '允许这项家庭查看权限？' : '取消这项家庭查看权限？',
      summary: enabled
          ? '$memberLabel 将能够按当前家庭规则使用这项查看权限。'
          : '$memberLabel 将不再能够通过这项家庭授权查看对应内容。',
      scope: permissionLabel,
      undo: enabled ? '之后可以再次取消授权。' : '之后可以重新授权。',
      confirmLabel: enabled ? '允许查看' : '取消授权',
      destructive: !enabled,
    );
  }

  factory SensitiveOperationSpec.familyMemberChange({
    required bool leaving,
    required String memberLabel,
  }) {
    return SensitiveOperationSpec(
      id: leaving ? 'family-leave' : 'family-remove',
      strength: SensitiveOperationStrength.permissionMutation,
      title: leaving ? '退出这个家庭？' : '移除这个家庭成员？',
      summary: leaving
          ? '退出后，你与家庭成员之间现有的共享授权会被清理。'
          : '移除后，与 $memberLabel 相关的家庭共享授权会被清理。',
      scope: leaving ? '当前账号在这个家庭中的成员关系' : '$memberLabel 的家庭成员关系',
      undo: '如需恢复关系，需要重新加入家庭并重新授权。',
      confirmLabel: leaving ? '退出家庭' : '移除成员',
      destructive: true,
    );
  }

  factory SensitiveOperationSpec.emergencyLocationStart({
    required String memberLabel,
    required String durationLabel,
  }) {
    return SensitiveOperationSpec(
      id: 'emergency-location-share',
      strength: SensitiveOperationStrength.sensitiveLocation,
      title: '开始临时位置共享？',
      summary: '$memberLabel 将在限定时间内获得临时位置查看能力。',
      scope: '共享当前位置，持续 $durationLabel；不会扩展为后台共享新能力。',
      undo: '可以随时停止共享；到期后服务端也会停止该临时能力。',
      confirmLabel: '开始共享位置',
    );
  }

  final String id;
  final SensitiveOperationStrength strength;
  final String title;
  final String summary;
  final String scope;
  final String undo;
  final String confirmLabel;
  final String? requiredPhrase;
  final bool destructive;
}

String sensitiveOperationSafeError(
  Object error, {
  String fallback = '操作暂时没有完成，请稍后重试',
}) {
  if (error is ProtocolException) {
    return '状态刚刚发生变化，请重新打开后再试';
  }
  if (error is ApiException) {
    if (error.statusCode == 401 || error.statusCode == 403) {
      return '你现在没有权限执行这个操作';
    }
    if (error.statusCode == 404 ||
        error.statusCode == 409 ||
        error.message.contains('STALE') ||
        error.message.contains('NOT_FOUND') ||
        error.message.contains('EXPIRED')) {
      return '状态刚刚发生变化，请重新打开后再试';
    }
  }
  return fallback;
}

Future<bool> showSensitiveOperationConfirmation(
  BuildContext context,
  SensitiveOperationSpec spec,
) async {
  final result = await showDialog<bool>(
    context: context,
    barrierDismissible: true,
    builder: (_) => _SensitiveOperationDialog(spec: spec),
  );
  return result == true;
}

class _SensitiveOperationDialog extends StatefulWidget {
  const _SensitiveOperationDialog({required this.spec});

  final SensitiveOperationSpec spec;

  @override
  State<_SensitiveOperationDialog> createState() =>
      _SensitiveOperationDialogState();
}

class _SensitiveOperationDialogState extends State<_SensitiveOperationDialog> {
  final TextEditingController controller = TextEditingController();

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final spec = widget.spec;
    final phrase = spec.requiredPhrase;
    final phraseMatches = phrase == null || controller.text.trim() == phrase;
    return AlertDialog(
      title: Text(spec.title),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(spec.summary),
            const SizedBox(height: JiYiSpacing.sm),
            Text('影响范围：${spec.scope}'),
            const SizedBox(height: JiYiSpacing.xs),
            Text('是否可撤销：${spec.undo}'),
            if (phrase != null) ...[
              const SizedBox(height: JiYiSpacing.md),
              Text('请输入“$phrase”确认这次不可逆操作。'),
              const SizedBox(height: JiYiSpacing.sm),
              TextField(
                key: ValueKey('${spec.id}-confirm-input'),
                controller: controller,
                autofocus: true,
                decoration: InputDecoration(
                  labelText: '确认文字',
                  hintText: phrase,
                ),
                onChanged: (_) => setState(() {}),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          key: ValueKey('${spec.id}-confirm-cancel'),
          onPressed: () => Navigator.pop(context, false),
          child: const Text('取消'),
        ),
        FilledButton(
          key: ValueKey('${spec.id}-confirm-submit'),
          onPressed: phraseMatches ? () => Navigator.pop(context, true) : null,
          style: spec.destructive
              ? FilledButton.styleFrom(
                  backgroundColor: Theme.of(context).colorScheme.error,
                  foregroundColor: Theme.of(context).colorScheme.onError,
                )
              : null,
          child: Text(spec.confirmLabel),
        ),
      ],
    );
  }
}
