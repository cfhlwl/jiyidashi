import 'package:flutter/material.dart';

import 'api_client.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';

class MemoryDetailPage extends StatefulWidget {
  const MemoryDetailPage({
    super.key,
    required this.api,
    required this.memoryId,
  });

  final JiYiApiClient api;
  final String memoryId;

  @override
  State<MemoryDetailPage> createState() => _MemoryDetailPageState();
}

class _MemoryDetailPageState extends State<MemoryDetailPage> {
  _MemoryDetailView? memory;
  String? placeName;
  bool loading = true;
  bool mutating = false;
  String? error;
  String? status;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant MemoryDetailPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.memoryId != widget.memoryId) _load();
  }

  bool _sessionCurrent(int version, String? owner) =>
      mounted &&
      widget.api.sessionVersion == version &&
      widget.api.authenticatedUserId == owner;

  Future<void> _load() async {
    final version = widget.api.sessionVersion;
    final owner = widget.api.authenticatedUserId;
    if (owner == null || owner.trim().isEmpty) {
      setState(() {
        loading = false;
        error = '请先登录';
      });
      return;
    }
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final raw = await widget.api.getMemory(widget.memoryId);
      if (!_sessionCurrent(version, owner)) return;
      final parsed = _MemoryDetailView.parse(
        raw,
        expectedId: widget.memoryId,
        expectedOwnerId: owner,
      );

      String? resolvedPlace;
      final placeId = parsed.placeId;
      if (placeId != null) {
        try {
          final rawPlace = await widget.api.getPlaceDetail(placeId, limit: 1);
          if (!_sessionCurrent(version, owner)) return;
          final place = rawPlace['place'];
          if (place is Map<String, dynamic> &&
              place['id']?.toString().toLowerCase() == placeId.toLowerCase()) {
            final name = place['name']?.toString().trim() ?? '';
            if (name.isNotEmpty) resolvedPlace = name;
          }
        } catch (_) {
          if (!_sessionCurrent(version, owner)) return;
        }
      }

      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        memory = parsed;
        placeName = resolvedPlace;
        loading = false;
      });
    } on ApiException catch (exc) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        loading = false;
        error = exc.statusCode == 404
            ? '这条记忆已经不存在'
            : '这条记忆暂时无法打开，可以稍后重试';
      });
    } on ProtocolException {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        loading = false;
        error = '这条记忆的数据暂时无法识别，可以重新打开后再试';
      });
    } catch (_) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        loading = false;
        error = '这条记忆暂时无法打开，可以稍后重试';
      });
    }
  }

  Future<void> _edit() async {
    final current = memory;
    if (current == null || mutating) return;
    final draft = await showDialog<_MemoryDetailDraft>(
      context: context,
      builder: (_) => _MemoryDetailEditor(memory: current),
    );
    if (draft == null || !mounted) return;

    final version = widget.api.sessionVersion;
    final owner = widget.api.authenticatedUserId;
    setState(() {
      mutating = true;
      error = null;
      status = null;
    });
    try {
      await widget.api.updateMemory(
        current.id,
        expectedRevision: current.editRevision,
        title: draft.title,
        content: draft.content,
      );
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        mutating = false;
        status = '修改已保存';
      });
      await _load();
    } on ApiException catch (exc) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        mutating = false;
        error = exc.statusCode == 409
            ? '内容刚刚发生了变化，请重新打开后再试'
            : '修改暂时无法保存，可以稍后重试';
      });
    } catch (_) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        mutating = false;
        error = '修改暂时无法保存，可以稍后重试';
      });
    }
  }

  Future<void> _delete() async {
    final current = memory;
    if (current == null || mutating) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('删除这条记忆？'),
        content: const Text('删除后，这条记忆将不能再被找回，也不会继续用于后续查找。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton.icon(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
            onPressed: () => Navigator.of(context).pop(true),
            icon: const Icon(Icons.delete_outline),
            label: const Text('确认删除'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    final version = widget.api.sessionVersion;
    final owner = widget.api.authenticatedUserId;
    setState(() {
      mutating = true;
      error = null;
      status = null;
    });
    try {
      await widget.api.deleteMemory(current.id);
      if (!_sessionCurrent(version, owner)) return;
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (_) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        mutating = false;
        error = '删除暂时无法完成，可以稍后重试';
      });
    } catch (_) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        mutating = false;
        error = '删除暂时无法完成，可以稍后重试';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final current = memory;
    return Scaffold(
      appBar: AppBar(title: const Text('记忆详情')),
      body: SafeArea(
        child: JiYiPageFrame(
          title: '记忆详情',
          subtitle: '回看你当时留下的内容。',
          hero: current == null
              ? null
              : JiYiHeroHeader(
                  eyebrow: '迹忆 · 记忆',
                  title: current.title ?? '一段记忆',
                  subtitle: _formatDateTime(current.occurredAt),
                  icon: _memoryIcon(current.memoryType),
                ),
          child: loading
              ? const Center(child: CircularProgressIndicator())
              : error != null && current == null
                  ? Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        JiYiStatusBanner(
                          kind: JiYiStatusKind.error,
                          message: error!,
                        ),
                        const SizedBox(height: JiYiSpacing.md),
                        OutlinedButton.icon(
                          onPressed: _load,
                          icon: const Icon(Icons.refresh),
                          label: const Text('重新打开'),
                        ),
                      ],
                    )
                  : current == null
                      ? const JiYiEmptyState(
                          icon: Icons.auto_stories_outlined,
                          title: '这条记忆不可用',
                          message: '可以返回记忆页重新查找。',
                        )
                      : _ready(current),
        ),
      ),
    );
  }

  Widget _ready(_MemoryDetailView current) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (error != null) ...[
          JiYiStatusBanner(kind: JiYiStatusKind.error, message: error!),
          const SizedBox(height: JiYiSpacing.sm),
        ],
        if (status != null) ...[
          JiYiStatusBanner(kind: JiYiStatusKind.success, message: status!),
          const SizedBox(height: JiYiSpacing.sm),
        ],
        JiYiSectionCard(
          title: '记录',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _DetailRow(label: '类型', value: _memoryTypeLabel(current.memoryType)),
              _DetailRow(label: '时间', value: _formatDateTime(current.occurredAt)),
              if (current.placeId != null)
                _DetailRow(label: '地点', value: placeName ?? '已关联地点'),
              const SizedBox(height: JiYiSpacing.sm),
              Text(
                current.content,
                style: Theme.of(context).textTheme.bodyLarge?.copyWith(height: 1.6),
              ),
            ],
          ),
        ),
        const SizedBox(height: JiYiSpacing.md),
        JiYiSectionCard(
          title: '管理',
          subtitle: '编辑会保留原始记录；删除会影响后续查找。',
          child: Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: mutating ? null : _edit,
                  icon: const Icon(Icons.edit_outlined),
                  label: const Text('编辑'),
                ),
              ),
              const SizedBox(width: JiYiSpacing.sm),
              Expanded(
                child: TextButton.icon(
                  onPressed: mutating ? null : _delete,
                  icon: const Icon(Icons.delete_outline),
                  label: const Text('删除'),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _MemoryDetailDraft {
  const _MemoryDetailDraft({required this.title, required this.content});

  final String? title;
  final String content;
}

class _MemoryDetailEditor extends StatefulWidget {
  const _MemoryDetailEditor({required this.memory});

  final _MemoryDetailView memory;

  @override
  State<_MemoryDetailEditor> createState() => _MemoryDetailEditorState();
}

class _MemoryDetailEditorState extends State<_MemoryDetailEditor> {
  late final TextEditingController title =
      TextEditingController(text: widget.memory.title ?? '');
  late final TextEditingController content =
      TextEditingController(text: widget.memory.content);
  String? error;

  @override
  void dispose() {
    title.dispose();
    content.dispose();
    super.dispose();
  }

  void _submit() {
    final body = content.text.trim();
    final heading = title.text.trim();
    if (body.isEmpty) {
      setState(() => error = '记忆内容不能为空');
      return;
    }
    Navigator.of(context).pop(
      _MemoryDetailDraft(
        title: heading.isEmpty ? null : heading,
        content: body,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('编辑记忆'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: title,
              maxLength: 240,
              decoration: const InputDecoration(labelText: '标题（可选）'),
            ),
            TextField(
              controller: content,
              minLines: 4,
              maxLines: 8,
              maxLength: 20000,
              decoration: InputDecoration(
                labelText: '内容',
                alignLabelWithHint: true,
                errorText: error,
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('取消'),
        ),
        FilledButton(onPressed: _submit, child: const Text('保存')),
      ],
    );
  }
}

class _DetailRow extends StatelessWidget {
  const _DetailRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: JiYiSpacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 64,
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}

class _MemoryDetailView {
  const _MemoryDetailView({
    required this.id,
    required this.ownerId,
    required this.memoryType,
    required this.title,
    required this.content,
    required this.occurredAt,
    required this.placeId,
    required this.editRevision,
  });

  final String id;
  final String ownerId;
  final String memoryType;
  final String? title;
  final String content;
  final String occurredAt;
  final String? placeId;
  final int editRevision;

  static final RegExp _uuid = RegExp(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    caseSensitive: false,
  );

  factory _MemoryDetailView.parse(
    Map<String, dynamic> raw, {
    required String expectedId,
    required String expectedOwnerId,
  }) {
    String requiredUuid(String key) {
      final value = raw[key];
      if (value is! String || !_uuid.hasMatch(value)) {
        throw ProtocolException('记忆数据格式不正确');
      }
      return value;
    }

    final id = requiredUuid('id');
    final ownerId = requiredUuid('user_id');
    if (id.toLowerCase() != expectedId.toLowerCase() ||
        ownerId.toLowerCase() != expectedOwnerId.toLowerCase()) {
      throw ProtocolException('记忆归属不匹配');
    }

    final type = raw['memory_type'];
    final content = raw['content'];
    final occurredAt = raw['occurred_at'];
    final revision = raw['edit_revision'];
    final title = raw['title'];
    final place = raw['place_id'];
    if (type is! String ||
        type.trim().isEmpty ||
        content is! String ||
        content.trim().isEmpty ||
        occurredAt is! String ||
        DateTime.tryParse(occurredAt) == null ||
        revision is! int ||
        revision < 0 ||
        (title != null && title is! String) ||
        (place != null && (place is! String || !_uuid.hasMatch(place)))) {
      throw ProtocolException('记忆数据格式不正确');
    }

    return _MemoryDetailView(
      id: id,
      ownerId: ownerId,
      memoryType: type,
      title: title is String && title.trim().isNotEmpty ? title.trim() : null,
      content: content.trim(),
      occurredAt: occurredAt,
      placeId: place as String?,
      editRevision: revision,
    );
  }
}

String _memoryTypeLabel(String value) => switch (value) {
      'NOTE' => '文字记录',
      'VOICE' => '语音记录',
      'PHOTO' => '照片记录',
      'PLACE' => '地点记录',
      'OBJECT_LOCATION' => '物品位置',
      'REMINDER' => '提醒记录',
      'EVENT' => '事件记录',
      _ => '记忆',
    };

IconData _memoryIcon(String value) => switch (value) {
      'VOICE' => Icons.mic_none_outlined,
      'PHOTO' => Icons.photo_outlined,
      'PLACE' => Icons.place_outlined,
      'OBJECT_LOCATION' => Icons.inventory_2_outlined,
      _ => Icons.auto_stories_outlined,
    };

String _formatDateTime(String value) {
  final parsed = DateTime.tryParse(value);
  if (parsed == null) return '时间未知';
  final local = parsed.toLocal();
  String two(int v) => v.toString().padLeft(2, '0');
  return '${local.year}-${two(local.month)}-${two(local.day)} '
      '${two(local.hour)}:${two(local.minute)}';
}
