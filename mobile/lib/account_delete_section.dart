import 'dart:math';

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'sensitive_operation_confirmation.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';

String _newAccountDeleteRequestId() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  final hex = bytes.map((value) => value.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
      '${hex.substring(12, 16)}-${hex.substring(16, 20)}-'
      '${hex.substring(20)}';
}

class AccountDeleteSection extends StatefulWidget {
  const AccountDeleteSection({
    super.key,
    required this.api,
    required this.onIntentConfirmed,
    required this.onDeleted,
    this.resumeInProgress = false,
  });

  final JiYiApiClient api;
  // [人工注释][S1-022-FIX-002] 用户已经输入“注销账号”后，先清本机 owner-scoped
  // payload/state 并冻结同步，再向服务端推进不可逆注销；消除“服务器已删但本机残留”的崩溃窗口。
  final Future<void> Function() onIntentConfirmed;
  final Future<void> Function() onDeleted;
  final bool resumeInProgress;

  @override
  State<AccountDeleteSection> createState() => _AccountDeleteSectionState();
}

class _AccountDeleteSectionState extends State<AccountDeleteSection> {
  String? requestId;
  bool deleting = false;
  bool confirming = false;
  String? message;
  bool messageIsError = false;
  int? retryAfterSeconds;
  bool gatePrepared = false;
  bool intentPrepared = false;

  @override
  void initState() {
    super.initState();
    // 恢复登录只会在服务端已存在 AccountDeletionOperation 时进入该模式。
    gatePrepared = widget.resumeInProgress;
  }

  Future<bool> _confirm() {
    return showSensitiveOperationConfirmation(
      context,
      const SensitiveOperationSpec.accountDelete(),
    );
  }

  Future<void> startOrContinue({bool requireConfirmation = false}) async {
    if (deleting || confirming) return;
    if (requireConfirmation) {
      setState(() => confirming = true);
      var confirmed = false;
      try {
        confirmed = await _confirm();
      } finally {
        if (mounted) setState(() => confirming = false);
      }
      if (!mounted || !confirmed) return;
    }
    requestId ??= _newAccountDeleteRequestId();

    setState(() {
      deleting = true;
      message = null;
      messageIsError = false;
    });

    try {
      if (!gatePrepared) {
        try {
          // [人工注释][S1-022-FIX-002] PREPARE 必须先于本机 purge：
          // 一旦服务器 gate 落盘，即使此后 App 崩溃，也能重新登录拿恢复 token 继续注销；
          // 但 local_cleanup_ready=false 时服务端绝不推进 S1-021/身份删除。
          final prepared = await widget.api.deleteAccount(
            requestId: requestId!,
            localCleanupReady: false,
          );
          final canonical = prepared['request_id']?.toString().trim();
          if (canonical != null && canonical.isNotEmpty) {
            requestId = canonical;
          }
          if (prepared['completed'] == true) {
            // 只会发生在旧 token 重放“已经完成的注销”时；先清本机再退出。
            await widget.onIntentConfirmed();
            intentPrepared = true;
            await widget.onDeleted();
            return;
          }
          gatePrepared = true;
        } on TransportException {
          if (!mounted) return;
          setState(() {
            messageIsError = false;
            message = '暂时无法确认注销保护是否已建立；可以直接继续注销，重复 PREPARE 不会创建第二条任务。';
          });
          return;
        } on ApiException catch (exc) {
          if (!mounted) return;
          setState(() {
            messageIsError = true;
            message = sensitiveOperationSafeError(
              exc,
              fallback: '账号注销暂时没有完成，请重新打开后再试',
            );
          });
          return;
        } on ProtocolException catch (exc) {
          if (!mounted) return;
          setState(() {
            messageIsError = true;
            message = sensitiveOperationSafeError(exc);
          });
          return;
        } catch (_) {
          if (!mounted) return;
          setState(() {
            messageIsError = true;
            message = '暂时无法建立安全注销保护，请稍后继续。';
          });
          return;
        }
      }

      if (!intentPrepared) {
        try {
          // durable gate 已存在后才清本机；清理失败时账号继续保持 423 锁定，可重试恢复。
          await widget.onIntentConfirmed();
          intentPrepared = true;
        } catch (_) {
          if (mounted) {
            setState(() {
              messageIsError = true;
              message = '账号已进入注销保护，但本机数据清理尚未完成；请再次继续注销。';
            });
          }
          return;
        }
      }

      try {
        final response = await widget.api.deleteAccount(
          requestId: requestId!,
          localCleanupReady: true,
        );
        final canonical = response['request_id']?.toString().trim();
        if (canonical != null && canonical.isNotEmpty) {
          requestId = canonical;
        }
        if (response['completed'] == true) {
          await widget.onDeleted();
          return;
        }

        final rawRetry = response['retry_after_seconds'];
        retryAfterSeconds = rawRetry is int ? rawRetry : null;
        if (!mounted) return;
        setState(() {
          messageIsError = false;
          message = retryAfterSeconds != null && retryAfterSeconds! > 0
              ? '账号正在安全清理数据，请约 ${retryAfterSeconds!} 秒后继续注销。'
              : '账号正在安全清理数据，请稍后点击“继续注销”。';
        });
      } on TransportException {
        if (!mounted) return;
        // requestId 不清空；响应丢失后重试必须继续同一个 destructive intent。
        setState(() {
          messageIsError = false;
          message = '暂时无法确认注销进度；可以直接继续注销，重复请求不会创建第二次删除。';
        });
      } on ApiException catch (exc) {
        if (!mounted) return;
        setState(() {
          messageIsError = true;
          message = sensitiveOperationSafeError(
            exc,
            fallback: '账号注销暂时没有完成，请重新打开后再试',
          );
        });
      } on ProtocolException catch (exc) {
        if (!mounted) return;
        setState(() {
          messageIsError = true;
          message = sensitiveOperationSafeError(exc);
        });
      } catch (_) {
        if (!mounted) return;
        setState(() {
          messageIsError = true;
          message = '注销请求尚未完成；本机数据已按确认清理，请再次继续注销。';
        });
      }
    } finally {
      // [人工注释][S1-022-FIX-003] deleting 覆盖整个 PREPARE→LOCAL PURGE→COMMIT
      // 生命周期；任何阶段提前 return/异常都必须释放 busy，否则 UI 会永久停在“正在注销…”，
      // 用户也无法继续恢复已经建立的 durable account gate。
      if (mounted) {
        setState(() => deleting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final inProgress = widget.resumeInProgress || requestId != null;
    return JiYiSectionCard(
      leading: Icon(
        Icons.person_off_outlined,
        color: Theme.of(context).colorScheme.error,
      ),
      title: '注销账号',
      subtitle: '永久删除账号和属于你的数据。此操作不可撤销。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (message != null) ...[
            JiYiStatusBanner(
              kind: messageIsError
                  ? JiYiStatusKind.error
                  : JiYiStatusKind.warning,
              title: messageIsError ? '注销尚未完成' : '注销进行中',
              message: message!,
            ),
            const SizedBox(height: JiYiSpacing.sm),
          ],
          OutlinedButton.icon(
            key: const ValueKey('account-delete-open'),
            onPressed: deleting || confirming
                ? null
                : () => startOrContinue(requireConfirmation: !inProgress),
            style: OutlinedButton.styleFrom(
              foregroundColor: Theme.of(context).colorScheme.error,
              side: BorderSide(color: Theme.of(context).colorScheme.error),
            ),
            // Keep confirmation itself animation-free. The modal already blocks
            // interaction, and an indeterminate spinner would make widget tests (and
            // accessibility settle semantics) wait forever while the dialog is open.
            icon: deleting
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.person_off_outlined),
            label: Text(
              confirming
                  ? '正在确认…'
                  : deleting
                      ? '正在注销…'
                      : (inProgress ? '继续注销' : '永久注销账号'),
            ),
          ),
        ],
      ),
    );
  }
}
