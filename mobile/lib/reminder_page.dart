import 'dart:math';

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';

String _newReminderClientUuid() {
  // [人工注释][S1-025] 不引入额外 UUID 依赖；按 RFC 4122 v4 位规则生成 16 字节随机键。
  // 此键只标识一次客户端 mutation，不承载身份、时间或业务含义。
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  final hex = bytes.map((value) => value.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
      '${hex.substring(12, 16)}-${hex.substring(16, 20)}-'
      '${hex.substring(20)}';
}

class _ReminderCreateDialog extends StatefulWidget {
  const _ReminderCreateDialog({
    required this.api,
    required this.memoryId,
    required this.initialTitle,
  });

  final JiYiApiClient api;
  final String memoryId;
  final String initialTitle;

  @override
  State<_ReminderCreateDialog> createState() => _ReminderCreateDialogState();
}

class _ReminderCreateDialogState extends State<_ReminderCreateDialog> {
  late final TextEditingController titleController =
      TextEditingController(text: widget.initialTitle);
  final TextEditingController contentController = TextEditingController();
  int delayMinutes = 60;
  String? error;
  bool saving = false;

  String? _attemptSignature;
  String? _attemptClientUuid;
  DateTime? _attemptRemindAt;

  @override
  void dispose() {
    titleController.dispose();
    contentController.dispose();
    super.dispose();
  }

  Future<void> save() async {
    final title = titleController.text.trim();
    final content = contentController.text.trim();
    if (title.isEmpty) {
      setState(() => error = '提醒标题不能为空');
      return;
    }

    final signature = '$title\u0000$content\u0000$delayMinutes';
    if (_attemptSignature != signature) {
      // [人工注释][S1-025] 第一次提交冻结 UUID + 绝对提醒时刻。
      // 若 HTTP 响应丢失，用户原样再次点击“设置提醒”会复用二者；
      // 若用户修改任何业务字段，则这是新意图，必须生成新的 mutation key。
      _attemptSignature = signature;
      _attemptClientUuid = _newReminderClientUuid();
      _attemptRemindAt = DateTime.now().add(Duration(minutes: delayMinutes));
    }

    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.api.createReminder(
        memoryId: widget.memoryId,
        title: title,
        content: content.isEmpty ? null : content,
        remindAt: _attemptRemindAt!,
        clientUuid: _attemptClientUuid!,
      );
      if (!mounted) return;
      Navigator.of(context).pop('✓ 提醒已设置；可点“查看提醒管理”完成或取消');
    } on ApiException catch (exc) {
      if (mounted) {
        setState(() {
          error = exc.statusCode == 409 &&
                  exc.message == 'IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST'
              ? '提醒内容已变化，请重新修改后提交'
              : exc.message;
        });
      }
    } catch (_) {
      if (mounted) {
        // transport/未知响应失败时不清空 attempt；原样重试必须继续使用同一 Idempotency-Key。
        setState(() => error = '暂时无法确认提醒是否保存；可直接再次点击“设置提醒”安全重试');
      }
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('为这条记忆设置提醒'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('提醒会继续绑定这条原始记忆；本阶段不创建重复任务或 Todo 项目。'),
            const SizedBox(height: JiYiSpacing.md),
            TextField(
              key: const ValueKey('reminder-title'),
              controller: titleController,
              enabled: !saving,
              maxLength: 240,
              decoration: const InputDecoration(labelText: '提醒标题'),
            ),
            const SizedBox(height: JiYiSpacing.sm),
            TextField(
              key: const ValueKey('reminder-content'),
              controller: contentController,
              enabled: !saving,
              maxLength: 2000,
              maxLines: 3,
              decoration: const InputDecoration(labelText: '备注（可选）'),
            ),
            const SizedBox(height: JiYiSpacing.sm),
            DropdownButtonFormField<int>(
              key: const ValueKey('reminder-delay'),
              initialValue: delayMinutes,
              decoration: const InputDecoration(labelText: '提醒时间'),
              items: const [
                DropdownMenuItem(value: 30, child: Text('30 分钟后')),
                DropdownMenuItem(value: 60, child: Text('1 小时后')),
                DropdownMenuItem(value: 180, child: Text('3 小时后')),
                DropdownMenuItem(value: 1440, child: Text('24 小时后')),
              ],
              onChanged: saving
                  ? null
                  : (value) {
                      if (value != null) setState(() => delayMinutes = value);
                    },
            ),
            if (error != null) ...[
              const SizedBox(height: JiYiSpacing.sm),
              JiYiStatusBanner(
                kind: JiYiStatusKind.error,
                title: '提醒尚未确认',
                message: error!,
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: saving ? null : () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          key: const ValueKey('reminder-save'),
          onPressed: saving ? null : save,
          child: Text(saving ? '保存中…' : '设置提醒'),
        ),
      ],
    );
  }
}

Future<String?> showMemoryReminderCreateFlow({
  required BuildContext context,
  required JiYiApiClient api,
  required String memoryId,
}) async {
  // [人工注释][S1-025] 创建入口先重新读取 Memory 当前快照；若 Memory 已删除/跨 owner，
  // 服务端 GET 直接失败，客户端不能用旧 query 结果伪造提醒。
  final memory = await api.getMemory(memoryId);
  if (!context.mounted) return null;

  final rawTitle = memory['title']?.toString().trim() ?? '';
  final rawContent = memory['content']?.toString().trim() ?? '';
  final fallbackTitle =
      rawContent.length > 60 ? rawContent.substring(0, 60) : rawContent;
  return showDialog<String>(
    context: context,
    builder: (dialogContext) => _ReminderCreateDialog(
      api: api,
      memoryId: memoryId,
      initialTitle: rawTitle.isNotEmpty ? rawTitle : fallbackTitle,
    ),
  );
}

class ReminderPage extends StatefulWidget {
  const ReminderPage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<ReminderPage> createState() => _ReminderPageState();
}

class _ReminderPageState extends State<ReminderPage> {
  List<Map<String, dynamic>> pending = const [];
  List<Map<String, dynamic>> history = const [];
  bool loading = true;
  String? activeReminderId;
  String? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<(List<Map<String, dynamic>>, List<Map<String, dynamic>>)> _fetchLists() async {
    // [人工注释][S1-025] PENDING 必须独立查询，不能让大量 DONE/CANCELLED 消耗同一个 LIMIT。
    final result = await Future.wait([
      widget.api.listReminders(status: 'PENDING', limit: 200),
      widget.api.listReminders(status: 'DONE', limit: 100),
      widget.api.listReminders(status: 'CANCELLED', limit: 100),
    ]);
    final nextHistory = <Map<String, dynamic>>[
      ...result[1],
      ...result[2],
    ]..sort((left, right) {
        final leftTime =
            DateTime.tryParse(left['created_at']?.toString() ?? '');
        final rightTime =
            DateTime.tryParse(right['created_at']?.toString() ?? '');
        if (leftTime == null && rightTime == null) return 0;
        if (leftTime == null) return 1;
        if (rightTime == null) return -1;
        return rightTime.compareTo(leftTime);
      });
    return (result[0], nextHistory);
  }

  Future<void> load() async {
    if (mounted) {
      setState(() {
        loading = true;
        error = null;
      });
    }
    try {
      final result = await _fetchLists();
      if (mounted) {
        setState(() {
          pending = result.$1;
          history = result.$2;
        });
      }
    } on ApiException catch (exc) {
      if (mounted) setState(() => error = exc.message);
    } catch (_) {
      if (mounted) setState(() => error = '暂时无法读取提醒');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> transition(String id, {required bool done}) async {
    setState(() {
      activeReminderId = id;
      error = null;
    });
    try {
      if (done) {
        await widget.api.completeReminder(id);
      } else {
        await widget.api.cancelReminder(id);
      }
      final result = await _fetchLists();
      if (mounted) {
        setState(() {
          pending = result.$1;
          history = result.$2;
        });
      }
    } on ApiException catch (exc) {
      if (mounted) setState(() => error = exc.message);
    } catch (_) {
      if (mounted) setState(() => error = '暂时无法更新提醒');
    } finally {
      if (mounted) setState(() => activeReminderId = null);
    }
  }

  String formatTime(Object? value) {
    final parsed = DateTime.tryParse(value?.toString() ?? '');
    if (parsed == null) return '时间未知';
    final local = parsed.toLocal();
    String two(int number) => number.toString().padLeft(2, '0');
    return '${local.year}-${two(local.month)}-${two(local.day)} '
        '${two(local.hour)}:${two(local.minute)}';
  }

  Widget reminderCard(Map<String, dynamic> item) {
    final id = item['id']?.toString() ?? '';
    final status = item['status']?.toString() ?? 'UNKNOWN';
    final busy = activeReminderId == id;
    final statusLabel = switch (status) {
      'PENDING' => '待提醒',
      'DONE' => '已完成',
      'CANCELLED' => '已取消',
      _ => status,
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: JiYiSpacing.sm),
      child: JiYiSectionCard(
        title: item['title']?.toString() ?? '未命名提醒',
        subtitle: '${formatTime(item['remind_at'])} · $statusLabel',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if ((item['content']?.toString().trim() ?? '').isNotEmpty)
              Text(item['content'].toString()),
            if (status == 'PENDING') ...[
              const SizedBox(height: JiYiSpacing.sm),
              Wrap(
                spacing: JiYiSpacing.sm,
                runSpacing: JiYiSpacing.sm,
                children: [
                  FilledButton.tonalIcon(
                    key: ValueKey('reminder-done-$id'),
                    onPressed: busy ? null : () => transition(id, done: true),
                    icon: const Icon(Icons.check_circle_outline),
                    label: const Text('标记完成'),
                  ),
                  OutlinedButton.icon(
                    key: ValueKey('reminder-cancel-$id'),
                    onPressed: busy ? null : () => transition(id, done: false),
                    icon: const Icon(Icons.cancel_outlined),
                    label: const Text('取消提醒'),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('提醒管理')),
      body: SafeArea(
        child: JiYiPageFrame(
          title: '提醒',
          subtitle: '只管理与记忆关联的一次性提醒，不扩展为 Todo 或日历。',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (error != null) ...[
                JiYiStatusBanner(
                  kind: JiYiStatusKind.error,
                  title: '提醒操作失败',
                  message: error!,
                ),
                const SizedBox(height: JiYiSpacing.md),
              ],
              if (loading && pending.isEmpty && history.isEmpty)
                const JiYiSectionCard(
                  child: Padding(
                    padding: EdgeInsets.symmetric(vertical: JiYiSpacing.md),
                    child: Center(child: CircularProgressIndicator()),
                  ),
                )
              else ...[
                Text('待提醒', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: JiYiSpacing.sm),
                if (pending.isEmpty)
                  const JiYiSectionCard(
                    child: Text('当前没有待处理提醒。'),
                  )
                else
                  ...pending.map(reminderCard),
                const SizedBox(height: JiYiSpacing.lg),
                Text('历史', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: JiYiSpacing.sm),
                if (history.isEmpty)
                  const JiYiSectionCard(
                    child: Text('还没有已完成或已取消的提醒。'),
                  )
                else
                  ...history.map(reminderCard),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
