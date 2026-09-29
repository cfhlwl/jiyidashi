// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';
import 'graph_page.dart';
import 'people_models.dart';
import 'v2_api.dart';
import 'v2_authority.dart';
import 'v2_widgets.dart';

class PersonDetailPage extends StatefulWidget {
  const PersonDetailPage({
    super.key,
    required this.api,
    required this.personId,
  });

  final JiYiApiClient api;
  final String personId;

  @override
  State<PersonDetailPage> createState() => _PersonDetailPageState();
}

class _PersonDetailPageState extends State<PersonDetailPage> {
  late final V2Api v2 = V2Api(widget.api);
  final V2Authority readAuthority = V2Authority();
  final V2Authority mutationAuthority = V2Authority();
  final V2OperationFlight mutationFlight = V2OperationFlight();

  V2Person? person;
  V2KnownDuration? duration;
  List<V2PersonMemoryTimelineRow> memories = const [];
  List<V2RelationshipProjection> relationships = const [];
  List<V2MemoryPickerItem> memoryChoices = const [];
  List<V2Person> peopleChoices = const [];
  bool loading = true;
  String? error;
  String? status;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(PersonDetailPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.personId != widget.personId) {
      readAuthority.invalidate();
      mutationAuthority.invalidate();
      mutationFlight.invalidate();
      _clear();
      _load();
    }
  }

  @override
  void dispose() {
    readAuthority.invalidate();
    mutationAuthority.invalidate();
    mutationFlight.invalidate();
    super.dispose();
  }

  void _clear() {
    person = null;
    duration = null;
    memories = const [];
    relationships = const [];
    memoryChoices = const [];
    peopleChoices = const [];
    error = null;
    status = null;
    loading = true;
  }

  bool _readCurrent(V2AuthoritySnapshot snapshot) =>
      mounted && readAuthority.isCurrent(widget.api, snapshot, snapshot.identity);

  bool _mutationCurrent(V2OperationContext operation) =>
      mounted &&
      mutationAuthority.isCurrent(
        widget.api,
        operation.snapshot,
        operation.snapshot.identity,
      ) &&
      mutationFlight.isCurrent(operation.token, widget.api);

  Future<void> _load() async {
    final identity = 'person:' + widget.personId;
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = readAuthority.capture(widget.api, identity);
    } catch (exc) {
      if (mounted) {
        setState(() {
          loading = false;
          error = exc.toString();
        });
      }
      return;
    }
    if (mounted) {
      setState(() {
        loading = true;
        error = null;
      });
    }
    try {
      final result = await Future.wait<Object>([
        v2.getPerson(widget.personId),
        v2.listPersonMemories(widget.personId, limit: 100),
        v2.listRelationships(widget.personId, limit: 100),
        v2.getKnownDuration(widget.personId),
        v2.listMemoryChoices(limit: 100),
        v2.listPeople(limit: 100),
      ]);
      if (!_readCurrent(snapshot)) return;
      setState(() {
        person = result[0] as V2Person;
        memories = result[1] as List<V2PersonMemoryTimelineRow>;
        relationships = result[2] as List<V2RelationshipProjection>;
        duration = result[3] as V2KnownDuration;
        memoryChoices = result[4] as List<V2MemoryPickerItem>;
        peopleChoices = result[5] as List<V2Person>;
        loading = false;
      });
    } catch (exc) {
      if (!_readCurrent(snapshot)) return;
      setState(() {
        loading = false;
        error = exc.toString();
      });
    }
  }

  Future<bool> _confirm(String title, String message, String confirm) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(confirm),
          ),
        ],
      ),
    );
    return result == true;
  }

  Future<void> _runMutation(
    String identity,
    Future<String?> Function() operation, {
    bool refresh = true,
  }) async {
    final context = beginV2Operation(
      widget.api,
      mutationAuthority,
      mutationFlight,
      identity,
    );
    if (context == null) return;
    if (mounted) setState(() { error = null; status = null; });
    try {
      final message = await operation();
      if (!_mutationCurrent(context)) return;
      if (message != null) setState(() => status = message);
      if (refresh) {
        await continueV2Operation(
          widget.api,
          mutationAuthority,
          context.snapshot,
          [() async => _load()],
        );
      }
    } catch (exc) {
      if (!_mutationCurrent(context)) return;
      setState(() => error = exc.toString());
    } finally {
      if (mutationFlight.end(context.token) && mounted) {
        setState(() {});
      }
    }
  }

  Future<void> _editPerson() async {
    final current = person;
    if (current == null) return;
    final draft = await showDialog<_PersonEditDraft>(
      context: context,
      builder: (_) => _PersonEditDialog(person: current),
    );
    if (draft == null || !mounted) return;
    await _runMutation('person:update:' + current.id, () async {
      final saved = await v2.updatePerson(
        current,
        displayName: draft.name,
        relationshipLabel: draft.relationshipLabel,
        note: draft.note,
        aliases: draft.aliases,
      );
      return '已保存人物：' + saved.displayName;
    });
  }

  Future<void> _deletePerson() async {
    final current = person;
    if (current == null) return;
    final ok = await _confirm(
      '删除人物？',
      '将删除“' + current.displayName + '”及其人物关联。明确的 Memory 本身不会因此删除。',
      '删除',
    );
    if (!ok || !mounted) return;
    await _runMutation(
      'person:delete:' + current.id,
      () async {
        await v2.deletePerson(current.id);
        if (mounted) Navigator.of(context).pop();
        return null;
      },
      refresh: false,
    );
  }

  Future<void> _linkMemory() async {
    final linked = memories.map((row) => row.link.memoryId.toLowerCase()).toSet();
    final choices = memoryChoices
        .where((item) => !linked.contains(item.id.toLowerCase()))
        .toList(growable: false);
    if (choices.isEmpty) {
      setState(() => status = '没有可继续关联的明确 Memory');
      return;
    }
    final draft = await showDialog<_MemoryLinkDraft>(
      context: context,
      builder: (_) => _MemoryLinkDialog(choices: choices),
    );
    if (draft == null || !mounted) return;
    await _runMutation(
      'person:link:' + widget.personId + ':' + draft.memoryId,
      () async {
        await v2.linkPersonMemory(
          personId: widget.personId,
          memoryId: draft.memoryId,
          relationKind: draft.relationKind,
        );
        return '记忆已关联';
      },
    );
  }

  Future<void> _changeMemoryRelation(
    V2PersonMemoryTimelineRow row,
    String relationKind,
  ) async {
    await _runMutation(
      'person:memory:update:' + row.link.id,
      () async {
        await v2.updatePersonMemory(
          link: row.link,
          relationKind: relationKind,
        );
        return '人物记忆关系已更新';
      },
    );
  }

  Future<void> _unlinkMemory(V2PersonMemoryTimelineRow row) async {
    final ok = await _confirm(
      '取消记忆关联？',
      '只删除人物与这条 Memory 的显式关系，不删除 Memory。',
      '取消关联',
    );
    if (!ok || !mounted) return;
    await _runMutation(
      'person:memory:unlink:' + row.link.id,
      () async {
        await v2.unlinkPersonMemory(
          personId: row.link.personId,
          memoryId: row.link.memoryId,
        );
        return '记忆关联已取消';
      },
    );
  }

  Future<void> _createRelationship() async {
    final related = relationships
        .map((item) => item.otherPersonId.toLowerCase())
        .toSet();
    final candidates = peopleChoices
        .where(
          (item) =>
              item.id.toLowerCase() != widget.personId.toLowerCase() &&
              !related.contains(item.id.toLowerCase()),
        )
        .toList(growable: false);
    if (candidates.isEmpty) {
      setState(() => status = '没有可新建关系的其他人物');
      return;
    }
    final draft = await showDialog<_RelationshipDraft>(
      context: context,
      builder: (_) => _RelationshipDialog(candidates: candidates),
    );
    if (draft == null || !mounted || draft.otherPersonId == null) return;
    await _runMutation(
      'relationship:create:' + widget.personId + ':' + draft.otherPersonId!,
      () async {
        await v2.createRelationship(
          personAId: widget.personId,
          personBId: draft.otherPersonId!,
          kind: draft.kind,
          customLabel: draft.customLabel,
          note: draft.note,
        );
        return '人物关系已创建';
      },
    );
  }

  Future<void> _editRelationship(V2RelationshipProjection projection) async {
    final operation = beginV2Operation(
      widget.api,
      mutationAuthority,
      mutationFlight,
      'relationship:update:' + projection.relationshipId,
    );
    if (operation == null) return;
    try {
      final full = await v2.getRelationship(projection.relationshipId);
      if (!_mutationCurrent(operation) || !mounted) return;
      final draft = await showDialog<_RelationshipDraft>(
        context: context,
        builder: (_) => _RelationshipDialog(
          initialKind: full.kind,
          initialCustomLabel: full.customLabel ?? '',
          initialNote: full.note ?? '',
        ),
      );
      if (draft == null || !_mutationCurrent(operation)) return;
      await v2.updateRelationship(
        full,
        kind: draft.kind,
        customLabel: draft.customLabel,
        note: draft.note,
      );
      if (!_mutationCurrent(operation)) return;
      setState(() => status = '人物关系已更新');
      await continueV2Operation(
        widget.api,
        mutationAuthority,
        operation.snapshot,
        [() async => _load()],
      );
    } catch (exc) {
      if (!_mutationCurrent(operation)) return;
      setState(() => error = exc.toString());
    } finally {
      if (mutationFlight.end(operation.token) && mounted) {
        setState(() {});
      }
    }
  }

  Future<void> _deleteRelationship(V2RelationshipProjection projection) async {
    final ok = await _confirm(
      '删除人物关系？',
      '将删除与“' + projection.otherPersonName + '”之间的显式人物关系。',
      '删除关系',
    );
    if (!ok || !mounted) return;
    await _runMutation(
      'relationship:delete:' + projection.relationshipId,
      () async {
        await v2.deleteRelationship(projection.relationshipId);
        return '人物关系已删除';
      },
    );
  }

  void _openGraph() {
    final current = person;
    if (current == null) return;
    Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => GraphNeighborhoodPage(
          api: widget.api,
          kind: 'PERSON',
          entityId: current.id,
          title: current.displayName,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final current = person;
    return Scaffold(
      appBar: AppBar(title: Text(current?.displayName ?? '人物详情')),
      body: SafeArea(
        child: JiYiPageFrame(
          title: current?.displayName ?? '人物详情',
          subtitle: '人物、别名、Memory 与关系都来自服务端明确记录，不从名称或时间自动推断。',
          child: loading
              ? const Center(child: CircularProgressIndicator())
              : error != null && current == null
                  ? V2ErrorState(message: error!, onRetry: _load)
                  : current == null
                      ? const JiYiEmptyState(
                          icon: Icons.person_off_outlined,
                          title: '人物不可用',
                          message: '这个人物当前不可访问。',
                        )
                      : _buildReady(current),
        ),
      ),
    );
  }

  Widget _buildReady(V2Person current) {
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
          title: '人物资料',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              V2KeyValue(label: '关系备注', value: current.relationshipLabel ?? '未设置'),
              V2KeyValue(
                label: '别名',
                value: current.aliases.isEmpty ? '无' : current.aliases.join(' / '),
              ),
              V2KeyValue(label: '备注', value: current.note ?? '无'),
              const SizedBox(height: JiYiSpacing.sm),
              Wrap(
                spacing: JiYiSpacing.sm,
                runSpacing: JiYiSpacing.sm,
                children: [
                  OutlinedButton.icon(
                    onPressed: mutationFlight.isPending ? null : _editPerson,
                    icon: const Icon(Icons.edit_outlined),
                    label: const Text('编辑人物'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _openGraph,
                    icon: const Icon(Icons.hub_outlined),
                    label: const Text('关系图谱'),
                  ),
                  TextButton.icon(
                    onPressed: mutationFlight.isPending ? null : _deletePerson,
                    icon: const Icon(Icons.delete_outline),
                    label: const Text('删除人物'),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: JiYiSpacing.md),
        _durationCard(),
        const SizedBox(height: JiYiSpacing.md),
        JiYiSectionCard(
          title: '关联记忆',
          subtitle: '只关联当前账号已有的明确 Memory；不会输入自由 UUID。',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              OutlinedButton.icon(
                onPressed: mutationFlight.isPending ? null : _linkMemory,
                icon: const Icon(Icons.add_link),
                label: const Text('关联 Memory'),
              ),
              if (memories.isEmpty)
                const Padding(
                  padding: EdgeInsets.only(top: JiYiSpacing.sm),
                  child: Text('还没有关联 Memory。'),
                ),
              for (final row in memories)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(row.memoryTitle ?? row.memoryContent),
                  subtitle: Text(
                    row.link.relationKind + ' · ' + row.occurredAt,
                  ),
                  trailing: PopupMenuButton<String>(
                    onSelected: (value) {
                      if (value == 'unlink') {
                        _unlinkMemory(row);
                      } else {
                        _changeMemoryRelation(row, value);
                      }
                    },
                    itemBuilder: (_) => [
                      if (row.link.relationKind != 'RELATED')
                        const PopupMenuItem(
                          value: 'RELATED',
                          child: Text('改为相关'),
                        ),
                      if (row.link.relationKind != 'MET')
                        const PopupMenuItem(
                          value: 'MET',
                          child: Text('改为见过'),
                        ),
                      const PopupMenuItem(
                        value: 'unlink',
                        child: Text('取消关联'),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: JiYiSpacing.md),
        JiYiSectionCard(
          title: '人物关系',
          subtitle: '不根据姓名、别名或共同出现自动创建关系。',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              OutlinedButton.icon(
                onPressed: mutationFlight.isPending ? null : _createRelationship,
                icon: const Icon(Icons.group_add_outlined),
                label: const Text('建立人物关系'),
              ),
              if (relationships.isEmpty)
                const Padding(
                  padding: EdgeInsets.only(top: JiYiSpacing.sm),
                  child: Text('还没有人物关系。'),
                ),
              for (final relation in relationships)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(relation.otherPersonName),
                  subtitle: Text(
                    (relation.customLabel ?? relation.kind) +
                        (relation.note == null ? '' : ' · ' + relation.note!),
                  ),
                  trailing: PopupMenuButton<String>(
                    onSelected: (value) {
                      if (value == 'edit') {
                        _editRelationship(relation);
                      } else {
                        _deleteRelationship(relation);
                      }
                    },
                    itemBuilder: (_) => const [
                      PopupMenuItem(value: 'edit', child: Text('编辑关系')),
                      PopupMenuItem(value: 'delete', child: Text('删除关系')),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _durationCard() {
    final value = duration;
    if (value == null) {
      return const JiYiSectionCard(
        title: '认识时长',
        child: Text('暂时无法读取认识时长。'),
      );
    }
    String message;
    if (value.status == 'KNOWN_SINCE_MET') {
      message = '至少 ' +
          value.elapsedDays.toString() +
          ' 天，从 ' +
          (value.atLeastSinceAt ?? '') +
          ' 起有可信“见过”证据。';
    } else if (value.status == 'RELATED_EVIDENCE_ONLY') {
      message = '有相关记录，但没有可信“见过”起点，不估算认识时长。';
    } else if (value.status == 'EVIDENCE_INCOMPLETE') {
      message = '相关证据不完整，暂不估算认识时长。';
    } else {
      message = '还没有足够可靠的认识时间证据。';
    }
    return JiYiSectionCard(
      title: '认识时长',
      subtitle: '这是确定性服务端投影，不是 AI 推断。',
      child: Text(message),
    );
  }
}

class _PersonEditDraft {
  const _PersonEditDraft({
    required this.name,
    required this.relationshipLabel,
    required this.note,
    required this.aliases,
  });

  final String name;
  final String relationshipLabel;
  final String note;
  final List<String> aliases;
}

class _PersonEditDialog extends StatefulWidget {
  const _PersonEditDialog({required this.person});

  final V2Person person;

  @override
  State<_PersonEditDialog> createState() => _PersonEditDialogState();
}

class _PersonEditDialogState extends State<_PersonEditDialog> {
  late final TextEditingController name =
      TextEditingController(text: widget.person.displayName);
  late final TextEditingController relation =
      TextEditingController(text: widget.person.relationshipLabel ?? '');
  late final TextEditingController note =
      TextEditingController(text: widget.person.note ?? '');
  late final TextEditingController aliases =
      TextEditingController(text: widget.person.aliases.join('\n'));
  String? error;

  @override
  void dispose() {
    name.dispose();
    relation.dispose();
    note.dispose();
    aliases.dispose();
    super.dispose();
  }

  void submit() {
    final display = name.text.trim();
    final aliasRows = aliases.text
        .split('\n')
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList(growable: false);
    if (display.isEmpty ||
        display.length > 200 ||
        aliasRows.length > 100 ||
        aliasRows.any((item) => item.length > 200)) {
      setState(() => error = '请检查人物名称和别名');
      return;
    }
    final lowered = <String>{};
    for (final alias in aliasRows) {
      if (!lowered.add(alias.toLowerCase())) {
        setState(() => error = '别名不能重复');
        return;
      }
    }
    Navigator.of(context).pop(
      _PersonEditDraft(
        name: display,
        relationshipLabel: relation.text.trim(),
        note: note.text.trim(),
        aliases: aliasRows,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('编辑人物'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(controller: name, decoration: const InputDecoration(labelText: '名称')),
            TextField(controller: relation, decoration: const InputDecoration(labelText: '关系备注')),
            TextField(
              controller: aliases,
              minLines: 2,
              maxLines: 5,
              decoration: const InputDecoration(labelText: '别名（每行一个）'),
            ),
            TextField(
              controller: note,
              minLines: 2,
              maxLines: 4,
              decoration: const InputDecoration(labelText: '备注'),
            ),
            if (error != null) Text(error!),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('取消')),
        FilledButton(onPressed: submit, child: const Text('保存')),
      ],
    );
  }
}

class _MemoryLinkDraft {
  const _MemoryLinkDraft({
    required this.memoryId,
    required this.relationKind,
  });

  final String memoryId;
  final String relationKind;
}

class _MemoryLinkDialog extends StatefulWidget {
  const _MemoryLinkDialog({required this.choices});

  final List<V2MemoryPickerItem> choices;

  @override
  State<_MemoryLinkDialog> createState() => _MemoryLinkDialogState();
}

class _MemoryLinkDialogState extends State<_MemoryLinkDialog> {
  late String memoryId = widget.choices.first.id;
  String relationKind = 'RELATED';

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('关联 Memory'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          DropdownButtonFormField<String>(
            initialValue: memoryId,
            decoration: const InputDecoration(labelText: 'Memory'),
            items: [
              for (final item in widget.choices)
                DropdownMenuItem(
                  value: item.id,
                  child: Text(item.title ?? item.content),
                ),
            ],
            onChanged: (value) {
              if (value != null) setState(() => memoryId = value);
            },
          ),
          DropdownButtonFormField<String>(
            initialValue: relationKind,
            decoration: const InputDecoration(labelText: '关系'),
            items: const [
              DropdownMenuItem(value: 'RELATED', child: Text('相关')),
              DropdownMenuItem(value: 'MET', child: Text('见过')),
            ],
            onChanged: (value) {
              if (value != null) setState(() => relationKind = value);
            },
          ),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('取消')),
        FilledButton(
          onPressed: () => Navigator.pop(
            context,
            _MemoryLinkDraft(memoryId: memoryId, relationKind: relationKind),
          ),
          child: const Text('关联'),
        ),
      ],
    );
  }
}

class _RelationshipDraft {
  const _RelationshipDraft({
    required this.otherPersonId,
    required this.kind,
    required this.customLabel,
    required this.note,
  });

  final String? otherPersonId;
  final String kind;
  final String customLabel;
  final String note;
}

class _RelationshipDialog extends StatefulWidget {
  const _RelationshipDialog({
    this.candidates = const [],
    this.initialKind = 'FRIEND',
    this.initialCustomLabel = '',
    this.initialNote = '',
  });

  final List<V2Person> candidates;
  final String initialKind;
  final String initialCustomLabel;
  final String initialNote;

  @override
  State<_RelationshipDialog> createState() => _RelationshipDialogState();
}

class _RelationshipDialogState extends State<_RelationshipDialog> {
  String? otherPersonId;
  late String kind = widget.initialKind;
  late final TextEditingController custom =
      TextEditingController(text: widget.initialCustomLabel);
  late final TextEditingController note =
      TextEditingController(text: widget.initialNote);
  String? error;

  @override
  void initState() {
    super.initState();
    if (widget.candidates.isNotEmpty) {
      otherPersonId = widget.candidates.first.id;
    }
  }

  @override
  void dispose() {
    custom.dispose();
    note.dispose();
    super.dispose();
  }

  void submit() {
    final customText = custom.text.trim();
    if (kind == 'OTHER' && customText.isEmpty) {
      setState(() => error = '“其他”关系必须填写自定义关系');
      return;
    }
    if (kind != 'OTHER' && customText.isNotEmpty) {
      setState(() => error = '只有“其他”关系可以填写自定义关系');
      return;
    }
    Navigator.of(context).pop(
      _RelationshipDraft(
        otherPersonId: otherPersonId,
        kind: kind,
        customLabel: customText,
        note: note.text.trim(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.candidates.isEmpty ? '编辑人物关系' : '建立人物关系'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (widget.candidates.isNotEmpty)
              DropdownButtonFormField<String>(
                initialValue: otherPersonId,
                decoration: const InputDecoration(labelText: '另一人物'),
                items: [
                  for (final item in widget.candidates)
                    DropdownMenuItem(value: item.id, child: Text(item.displayName)),
                ],
                onChanged: (value) => setState(() => otherPersonId = value),
              ),
            DropdownButtonFormField<String>(
              initialValue: kind,
              decoration: const InputDecoration(labelText: '关系类型'),
              items: const [
                DropdownMenuItem(value: 'FAMILY', child: Text('家人')),
                DropdownMenuItem(value: 'FRIEND', child: Text('朋友')),
                DropdownMenuItem(value: 'COLLEAGUE', child: Text('同事')),
                DropdownMenuItem(value: 'CLASSMATE', child: Text('同学')),
                DropdownMenuItem(value: 'OTHER', child: Text('其他')),
              ],
              onChanged: (value) {
                if (value != null) setState(() => kind = value);
              },
            ),
            if (kind == 'OTHER')
              TextField(
                controller: custom,
                maxLength: 120,
                decoration: const InputDecoration(labelText: '自定义关系'),
              ),
            TextField(
              controller: note,
              maxLength: 5000,
              minLines: 2,
              maxLines: 4,
              decoration: const InputDecoration(labelText: '备注'),
            ),
            if (error != null) Text(error!),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('取消')),
        FilledButton(onPressed: submit, child: const Text('保存')),
      ],
    );
  }
}
