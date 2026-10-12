// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_format.dart';
import '../ui/jiyi_tokens.dart';
import '../ui/jiyi_v3_components.dart';
import 'people_models.dart';
import 'person_detail_page.dart';
import 'v2_api.dart';
import 'v2_authority.dart';

class PeoplePage extends StatefulWidget {
  const PeoplePage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<PeoplePage> createState() => _PeoplePageState();
}

class _PeoplePageState extends State<PeoplePage> {
  late V2Api v2;
  JiYiApiClient? _boundApi;
  String? _boundOwner;
  int? _boundSessionVersion;
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
    v2 = V2Api(widget.api);
    _rememberAuthorityBinding();
    _load();
  }

  @override
  void didUpdateWidget(PeoplePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api != widget.api) {
      readAuthority.invalidate();
      mutationAuthority.invalidate();
      mutationFlight.invalidate();
      v2 = V2Api(widget.api);
      _rememberAuthorityBinding();
      people = const [];
      interactions = const [];
      error = null;
      status = null;
      loading = true;
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

  void _rememberAuthorityBinding() {
    _boundApi = widget.api;
    _boundOwner = widget.api.authenticatedUserId;
    _boundSessionVersion = widget.api.sessionVersion;
  }

  void _checkAuthorityBinding() {
    final changed = _boundApi != widget.api ||
        _boundOwner != widget.api.authenticatedUserId ||
        _boundSessionVersion != widget.api.sessionVersion;
    if (!changed) return;
    readAuthority.invalidate();
    mutationAuthority.invalidate();
    mutationFlight.invalidate();
    v2 = V2Api(widget.api);
    _rememberAuthorityBinding();
    people = const [];
    interactions = const [];
    error = null;
    status = null;
    loading = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _load();
    });
  }

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
    _checkAuthorityBinding();
    final theme = Theme.of(context);
    return V3PageScaffold(
      topBar: const V3TopBar(
        title: '重要的人',
        subtitle: '只有你主动添加的人会出现在这里',
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          V3SurfaceCard(
            color: JiYiSurfaceRoles.elevated,
            padding: const EdgeInsets.all(JiYiSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '把重要的人留在这里',
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.xs),
                Text(
                  '只展示你主动添加和维护的人物关系，不会根据姓名或共同出现自动猜测。',
                  style: theme.textTheme.bodyMedium,
                ),
                const SizedBox(height: JiYiSpacing.md),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    key: const ValueKey('people-add-person'),
                    onPressed: mutationFlight.isPending ? null : _createPerson,
                    icon: const Icon(Icons.person_add_alt_1),
                    label: const Text('添加重要的人'),
                  ),
                ),
              ],
            ),
          ),
          if (status != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            V3SurfaceCard(
              color: theme.colorScheme.primaryContainer,
              child: Text(status!),
            ),
          ],
          const SizedBox(height: JiYiSpacing.xl),
          if (loading)
            const V3StateSurface(
              variant: V3StateSurfaceVariant.loading,
              title: '正在读取重要的人',
              message: '只读取当前账号主动维护的人物资料。',
            )
          else if (error != null)
            V3StateSurface(
              variant: V3StateSurfaceVariant.error,
              title: '暂时无法读取人物',
              message: error!,
              primaryAction: V3StateAction(label: '重试', onPressed: _load),
            )
          else if (people.isEmpty)
            V3StateSurface(
              variant: V3StateSurfaceVariant.empty,
              icon: Icons.people_outline,
              title: '还没有记录重要的人',
              message: '先添加一个重要的人，再慢慢整理与 TA 有关的记忆和关系。',
              primaryAction: V3StateAction(
                label: '添加重要的人',
                icon: Icons.person_add_alt_1,
                onPressed: _createPerson,
              ),
            )
          else ...[
            const V3SectionHeader(
              title: '重要的人',
              count: people.length,
              subtitle: '资料和关系均来自你的主动记录。',
            ),
            const SizedBox(height: JiYiSpacing.sm),
            for (final person in people) ...[
              V3SurfaceCard(
                semanticLabel: '打开人物 ${person.displayName}',
                onTap: () => _openPerson(person),
                padding: const EdgeInsets.all(JiYiSpacing.md),
                child: Row(
                  children: [
                    Semantics(
                      label: '没有可信头像数据',
                      child: Container(
                        width: 56,
                        height: 56,
                        decoration: BoxDecoration(
                          color: theme.colorScheme.primaryContainer,
                          shape: BoxShape.circle,
                        ),
                        child: Icon(
                          Icons.person_outline,
                          color: theme.colorScheme.primary,
                        ),
                      ),
                    ),
                    const SizedBox(width: JiYiSpacing.md),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            person.displayName,
                            style: theme.textTheme.titleMedium?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(height: JiYiSpacing.xxs),
                          Text(
                            person.relationshipLabel ?? '还没有写下你们的关系',
                            style: theme.textTheme.bodyMedium,
                          ),
                          if (person.aliases.isNotEmpty)
                            Text(
                              '别名：' + person.aliases.join(' / '),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: theme.textTheme.bodySmall,
                            ),
                        ],
                      ),
                    ),
                    const Icon(Icons.chevron_right),
                  ],
                ),
              ),
              const SizedBox(height: JiYiSpacing.sm),
            ],
          ],
          if (interactions.isNotEmpty) ...[
            const SizedBox(height: JiYiSpacing.md),
            V3SectionHeader(
              title: '最近相关的记忆',
              subtitle: '来自你主动关联的记忆，不会自动推断。',
            ),
            const SizedBox(height: JiYiSpacing.sm),
            for (final row in interactions.take(8)) ...[
              V3SurfaceCard(
                padding: const EdgeInsets.all(JiYiSpacing.md),
                child: Row(
                  children: [
                    Icon(Icons.history, color: theme.colorScheme.primary),
                    const SizedBox(width: JiYiSpacing.md),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            row.personDisplayName,
                            style: theme.textTheme.titleSmall?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          Text('记录时间：' + jiyiDisplayDateTime(row.occurredAt)),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: JiYiSpacing.sm),
            ],
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
