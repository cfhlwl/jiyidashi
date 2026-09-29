// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';
import 'people_models.dart';
import 'person_detail_page.dart';
import 'v2_api.dart';
import 'v2_authority.dart';
import 'v2_widgets.dart';

class PeoplePage extends StatefulWidget {
  const PeoplePage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<PeoplePage> createState() => _PeoplePageState();
}

class _PeoplePageState extends State<PeoplePage> {
  late final V2Api v2 = V2Api(widget.api);
  final V2Authority readAuthority = V2Authority();
  final V2Authority mutationAuthority = V2Authority();
  final V2OperationFlight mutationFlight = V2OperationFlight();

  List<V2Person> people = const [];
  List<V2PersonInteraction> interactions = const [];
  bool loading = true;
  String? error;
  String? status;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    readAuthority.invalidate();
    mutationAuthority.invalidate();
    mutationFlight.invalidate();
    super.dispose();
  }

  bool _readCurrent(V2AuthoritySnapshot snapshot) =>
      mounted && readAuthority.isCurrent(widget.api, snapshot, snapshot.identity);

  bool _mutationCurrent(V2OperationContext context) =>
      mounted &&
      mutationAuthority.isCurrent(
        widget.api,
        context.snapshot,
        context.snapshot.identity,
      ) &&
      mutationFlight.isCurrent(context.token, widget.api);

  Future<void> _load() async {
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = readAuthority.capture(widget.api, 'people:list');
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
        v2.listPeople(limit: 100),
        v2.listRecentInteractions(limit: 30),
      ]);
      if (!_readCurrent(snapshot)) return;
      setState(() {
        people = result[0] as List<V2Person>;
        interactions = result[1] as List<V2PersonInteraction>;
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

  Future<void> _createPerson() async {
    final draft = await showDialog<_PersonDraft>(
      context: context,
      builder: (context) => const _PersonDialog(title: '添加重要的人'),
    );
    if (draft == null || !mounted) return;

    final operation = beginV2Operation(
      widget.api,
      mutationAuthority,
      mutationFlight,
      'person:create',
    );
    if (operation == null) return;
    setState(() => status = null);
    try {
      final created = await v2.createPerson(
        displayName: draft.name,
        relationshipLabel: draft.relationshipLabel,
        note: draft.note,
      );
      if (!_mutationCurrent(operation)) return;
      setState(() => status = '已保存：' + created.displayName);
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

  Future<void> _openPerson(V2Person person) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => PersonDetailPage(api: widget.api, personId: person.id),
      ),
    );
    if (mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    return JiYiPageFrame(
      title: '重要的人',
      subtitle: '记录生命中重要的人。只有你主动添加的人才会出现在这里。',
      hero: const JiYiHeroHeader(
        eyebrow: '迹忆 · 重要的人',
        title: '重要的人',
        subtitle: '记录生命中重要的人。只有你主动添加的人才会出现在这里。',
        icon: Icons.people_outline,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          FilledButton.icon(
            onPressed: mutationFlight.isPending ? null : _createPerson,
            icon: const Icon(Icons.person_add_alt_1),
            label: const Text('添加重要的人'),
          ),
          if (status != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            JiYiStatusBanner(kind: JiYiStatusKind.success, message: status!),
          ],
          const SizedBox(height: JiYiSpacing.md),
          if (loading)
            const Center(child: CircularProgressIndicator())
          else if (error != null)
            V2ErrorState(message: error!, onRetry: _load)
          else if (people.isEmpty)
            JiYiEmptyState(
              icon: Icons.people_outline,
              title: '还没有记录重要的人',
              message: '先添加一个重要的人，再慢慢整理与 TA 有关的记忆和关系。',
              action: OutlinedButton(
                onPressed: _createPerson,
                child: const Text('添加重要的人'),
              ),
            )
          else
            V2SectionCard(
              title: '重要的人',
              child: Column(
                children: [
                  for (final person in people)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const CircleAvatar(
                        child: Icon(Icons.person_outline),
                      ),
                      title: Text(person.displayName),
                      subtitle: Text(
                        person.aliases.isEmpty
                            ? (person.relationshipLabel ?? '还没有写下你们的关系')
                            : '别名：' + person.aliases.join(' / '),
                      ),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => _openPerson(person),
                    ),
                ],
              ),
            ),
          if (interactions.isNotEmpty) ...[
            const SizedBox(height: JiYiSpacing.md),
            V2SectionCard(
              title: '最近相关的记忆',
              subtitle: '来自你主动关联的记忆，不会自动推断。',
              child: Column(
                children: [
                  for (final row in interactions.take(8))
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.history),
                      title: Text(row.personDisplayName),
                      subtitle: Text('记录时间：' + row.occurredAt),
                    ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _PersonDraft {
  const _PersonDraft({
    required this.name,
    required this.relationshipLabel,
    required this.note,
  });

  final String name;
  final String relationshipLabel;
  final String note;
}

class _PersonDialog extends StatefulWidget {
  const _PersonDialog({
    required this.title,
  });

  final String title;

  @override
  State<_PersonDialog> createState() => _PersonDialogState();
}

class _PersonDialogState extends State<_PersonDialog> {
  final TextEditingController name = TextEditingController();
  final TextEditingController relation = TextEditingController();
  final TextEditingController note = TextEditingController();
  String? error;

  @override
  void dispose() {
    name.dispose();
    relation.dispose();
    note.dispose();
    super.dispose();
  }

  void submit() {
    final display = name.text.trim();
    if (display.isEmpty || display.length > 200) {
      setState(() => error = '姓名需为 1–200 个字符');
      return;
    }
    if (relation.text.trim().length > 120 || note.text.trim().length > 5000) {
      setState(() => error = '关系或备注内容过长');
      return;
    }
    Navigator.of(context).pop(
      _PersonDraft(
        name: display,
        relationshipLabel: relation.text.trim(),
        note: note.text.trim(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: name,
              maxLength: 200,
              decoration: const InputDecoration(labelText: '姓名'),
            ),
            TextField(
              controller: relation,
              maxLength: 120,
              decoration: const InputDecoration(labelText: '你们的关系（可选）'),
            ),
            TextField(
              controller: note,
              maxLength: 5000,
              minLines: 2,
              maxLines: 4,
              decoration: const InputDecoration(labelText: '备注（可选）'),
            ),
            if (error != null) Text(error!),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('取消'),
        ),
        FilledButton(onPressed: submit, child: const Text('保存')),
      ],
    );
  }
}
