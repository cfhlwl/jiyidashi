// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../ai_inference_presentation.dart';
import '../api_client.dart';
import '../ui/jiyi_format.dart';
import '../ui/jiyi_tokens.dart';
import '../ui/jiyi_v3_components.dart';
import 'life_editors.dart';
import 'life_models.dart';
import 'v2_api.dart';
import 'v2_authority.dart';

class LifeStageDetailPage extends StatefulWidget {
  const LifeStageDetailPage({
    super.key,
    required this.api,
    required this.stageId,
  });

  final JiYiApiClient api;
  final String stageId;

  @override
  State<LifeStageDetailPage> createState() => _LifeStageDetailPageState();
}

class _LifeStageDetailPageState extends State<LifeStageDetailPage> {
  late V2Api v2;
  JiYiApiClient? _boundApi;
  String? _boundOwner;
  int? _boundSessionVersion;
  String? _boundStageId;
  final V2Authority readAuthority = V2Authority();
  final V2Authority mutationAuthority = V2Authority();
  final V2Authority reasoningAuthority = V2Authority();
  final V2OperationFlight mutationFlight = V2OperationFlight();
  final V2OperationFlight reasoningFlight = V2OperationFlight();
  final TextEditingController question = TextEditingController();

  V2LifeStage? stage;
  List<V2LifeStageEvent> linkedEvents = const [];
  List<V2LifeEvent> events = const [];
  V2LongTermReasoning? reasoning;
  bool loading = true;
  bool reasoningLoading = false;
  String? error;
  String? status;

  @override
  void initState() {
    super.initState();
    v2 = V2Api(widget.api);
    _rememberBinding();
    _load();
  }

  @override
  void didUpdateWidget(LifeStageDetailPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.api, widget.api) ||
        oldWidget.stageId != widget.stageId) {
      _rebindAndReload();
    }
  }

  @override
  void dispose() {
    question.dispose();
    readAuthority.invalidate();
    mutationAuthority.invalidate();
    reasoningAuthority.invalidate();
    mutationFlight.invalidate();
    reasoningFlight.invalidate();
    super.dispose();
  }

  void _rememberBinding() {
    _boundApi = widget.api;
    _boundOwner = widget.api.authenticatedUserId;
    _boundSessionVersion = widget.api.sessionVersion;
    _boundStageId = widget.stageId;
  }

  bool get _bindingMatches =>
      identical(_boundApi, widget.api) &&
      _boundOwner == widget.api.authenticatedUserId &&
      _boundSessionVersion == widget.api.sessionVersion &&
      _boundStageId == widget.stageId;

  void _rebindAndReload() {
    readAuthority.invalidate();
    mutationAuthority.invalidate();
    reasoningAuthority.invalidate();
    mutationFlight.invalidate();
    reasoningFlight.invalidate();
    v2 = V2Api(widget.api);
    _rememberBinding();
    stage = null;
    linkedEvents = const [];
    events = const [];
    reasoning = null;
    error = null;
    status = null;
    loading = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _load();
    });
  }

  void _checkBinding() {
    if (!_bindingMatches) _rebindAndReload();
  }

  bool _readCurrent(V2AuthoritySnapshot snapshot) =>
      mounted &&
      _bindingMatches &&
      readAuthority.isCurrent(widget.api, snapshot, snapshot.identity);

  bool _mutationCurrent(V2OperationContext operation) =>
      mounted &&
      _bindingMatches &&
      mutationAuthority.isCurrent(
        widget.api,
        operation.snapshot,
        operation.snapshot.identity,
      ) &&
      mutationFlight.isCurrent(operation.token, widget.api);

  bool _reasoningCurrent(V2OperationContext operation) =>
      mounted &&
      _bindingMatches &&
      reasoningAuthority.isCurrent(
        widget.api,
        operation.snapshot,
        operation.snapshot.identity,
      ) &&
      reasoningFlight.isCurrent(operation.token, widget.api);

  void _invalidateReasoning() {
    reasoningAuthority.invalidate();
    reasoningFlight.invalidate();
    reasoning = null;
    reasoningLoading = false;
  }

  Future<void> _load() async {
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = readAuthority.capture(widget.api, 'life-stage:' + widget.stageId);
    } catch (exc) {
      if (mounted) setState(() { loading = false; error = exc.toString(); });
      return;
    }
    if (mounted) setState(() { loading = true; error = null; });
    try {
      final result = await Future.wait<Object>([
        v2.getLifeStage(widget.stageId),
        v2.listLifeStageEvents(widget.stageId, limit: 100),
        v2.listLifeEvents(limit: 100),
      ]);
      if (!_readCurrent(snapshot)) return;
      setState(() {
        stage = result[0] as V2LifeStage;
        linkedEvents = result[1] as List<V2LifeStageEvent>;
        events = result[2] as List<V2LifeEvent>;
        loading = false;
      });
    } catch (exc) {
      if (!_readCurrent(snapshot)) return;
      setState(() { loading = false; error = exc.toString(); });
    }
  }

  Future<void> _runMutation(
    String identity,
    Future<String?> Function() action, {
    bool refresh = true,
    bool invalidateReasoning = true,
    VoidCallback? onSuccess,
  }) async {
    final operation = beginV2Operation(
      widget.api,
      mutationAuthority,
      mutationFlight,
      identity,
    );
    if (operation == null) return;
    try {
      final message = await action();
      if (!_mutationCurrent(operation)) return;
      if (invalidateReasoning) _invalidateReasoning();
      if (message != null) setState(() => status = message);
      onSuccess?.call();
      if (refresh) {
        await continueV2Operation(
          widget.api,
          mutationAuthority,
          operation.snapshot,
          [() async => _load()],
        );
      }
    } catch (exc) {
      if (!_mutationCurrent(operation)) return;
      setState(() => error = exc.toString());
    } finally {
      if (mutationFlight.end(operation.token) && mounted) setState(() {});
    }
  }

  Future<void> _edit() async {
    final current = stage;
    if (current == null) return;
    LifeStageDraft? preserved;
    while (mounted) {
      final binding = (
        api: widget.api,
        owner: widget.api.authenticatedUserId,
        sessionVersion: widget.api.sessionVersion,
        stageId: current.id,
      );
      final draft = await showDialog<LifeStageDraft>(
        context: context,
        builder: (_) => LifeStageEditorDialog(
          initial: current,
          initialDraft: preserved,
          initialError: preserved == null ? null : '保存失败，请检查网络后重试。',
        ),
      );
      if (draft == null || !_dialogStillCurrent(binding)) return;
      final operation = beginV2Operation(
        widget.api,
        mutationAuthority,
        mutationFlight,
        'life-stage:update:' + current.id,
      );
      if (operation == null) return;
      try {
        final saved = await v2.updateLifeStage(
          current,
          kind: draft.kind,
          title: draft.title,
          customLabel: draft.customLabel,
          note: draft.note,
          startedAt: draft.startedAt,
          endedAt: draft.endedAt,
        );
        if (!_mutationCurrent(operation)) return;
        setState(() => status = '阶段已更新：' + saved.title);
        await continueV2Operation(
          widget.api,
          mutationAuthority,
          operation.snapshot,
          [() async => _load()],
        );
        return;
      } catch (exc) {
        if (!_mutationCurrent(operation)) return;
        preserved = draft;
        setState(() => error = exc.toString());
      } finally {
        if (mutationFlight.end(operation.token) && mounted) setState(() {});
      }
    }
  }

  bool _dialogStillCurrent(
    ({
      JiYiApiClient api,
      String? owner,
      int sessionVersion,
      String stageId,
    })
    binding,
  ) {
    return mounted &&
        identical(widget.api, binding.api) &&
        widget.api.authenticatedUserId == binding.owner &&
        widget.api.sessionVersion == binding.sessionVersion &&
        widget.stageId == binding.stageId &&
        _bindingMatches;
  }

  Future<void> _delete() async {
    final current = stage;
    if (current == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('删除人生阶段？'),
        content: Text('将删除“' + current.title + '”及其事件关联。此操作无法撤销。'),
        actions: [
          TextButton(
            key: const ValueKey('life-stage-delete-cancel'),
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            key: const ValueKey('life-stage-delete-confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await _runMutation(
      'life-stage:delete:' + current.id,
      () async {
        await v2.deleteLifeStage(current.id);
        return null;
      },
      refresh: false,
      onSuccess: () => Navigator.of(context).pop(),
    );
  }

  Future<void> _linkEvent() async {
    final linked = linkedEvents.map((item) => item.lifeEventId.toLowerCase()).toSet();
    final choices = events
        .where((item) => !linked.contains(item.id.toLowerCase()))
        .toList(growable: false);
    if (choices.isEmpty) {
      setState(() => status = '没有可继续关联的人生事件');
      return;
    }
    final selected = await showDialog<String>(
      context: context,
      builder: (context) {
        String value = choices.first.id;
        return StatefulBuilder(
          builder: (context, setLocal) => AlertDialog(
            title: const Text('关联人生经历'),
            content: DropdownButtonFormField<String>(
              key: const ValueKey('life-stage-event-picker'),
              initialValue: value,
              items: [
                for (final item in choices)
                  DropdownMenuItem(value: item.id, child: Text(item.title)),
              ],
              onChanged: (next) {
                if (next != null) setLocal(() => value = next);
              },
            ),
            actions: [
              TextButton(
                key: const ValueKey('life-stage-link-cancel'),
                onPressed: () => Navigator.pop(context),
                child: const Text('取消'),
              ),
              FilledButton(
                key: const ValueKey('life-stage-link-confirm'),
                onPressed: () => Navigator.pop(context, value),
                child: const Text('关联'),
              ),
            ],
          ),
        );
      },
    );
    if (selected == null || !mounted) return;
    await _runMutation(
      'life-stage:link:' + widget.stageId + ':' + selected,
      () async {
        await v2.linkLifeStageEvent(stageId: widget.stageId, eventId: selected);
        return '人生经历已关联';
      },
    );
  }

  Future<void> _unlinkEvent(V2LifeStageEvent item) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('取消事件关联？'),
        content: const Text('只删除阶段与事件之间的明确关系，不删除原始人生经历。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('取消关联'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await _runMutation(
      'life-stage:unlink:' + item.linkId,
      () async {
        await v2.unlinkLifeStageEvent(
          stageId: widget.stageId,
          eventId: item.lifeEventId,
        );
        return '事件关联已取消';
      },
    );
  }

  Future<void> _generateReasoning() async {
    final text = question.text.trim();
    if (text.isEmpty) {
      setState(() => error = '请输入要回顾的问题');
      return;
    }
    final operation = beginV2Operation(
      widget.api,
      reasoningAuthority,
      reasoningFlight,
      'reasoning:' + widget.stageId,
    );
    if (operation == null) return;
    setState(() {
      reasoningLoading = true;
      reasoning = null;
      error = null;
    });
    try {
      final result = await v2.reasonAboutLifeStage(
        stageId: widget.stageId,
        question: text,
      );
      if (!_reasoningCurrent(operation)) return;
      setState(() {
        reasoning = result;
        reasoningLoading = false;
      });
    } catch (exc) {
      if (!_reasoningCurrent(operation)) return;
      setState(() {
        error = exc.toString();
        reasoningLoading = false;
      });
    } finally {
      reasoningFlight.end(operation.token);
    }
  }

  V3StateSurfaceVariant _errorVariant() {
    final value = error ?? '';
    if (value.contains('网络') || value.contains('连接') || value.contains('Transport')) {
      return V3StateSurfaceVariant.offline;
    }
    if (value.contains('401') || value.contains('403') || value.contains('权限')) {
      return V3StateSurfaceVariant.blocked;
    }
    return V3StateSurfaceVariant.error;
  }

  @override
  Widget build(BuildContext context) {
    _checkBinding();
    final current = stage;
    return V3PageScaffold(
      topBar: V3TopBar(
        title: current?.title ?? '人生阶段',
        subtitle: current == null ? null : '把一段时光整理成可回看的线索',
        onBack: () => Navigator.of(context).maybePop(),
      ),
      child: loading
          ? const V3StateSurface(
              variant: V3StateSurfaceVariant.loading,
              title: '正在读取阶段详情',
              message: '正在核对阶段与关联经历。',
            )
          : error != null && current == null
              ? V3StateSurface(
                  variant: _errorVariant(),
                  title: '暂时无法读取阶段详情',
                  message: '请稍后重试；当前不会用猜测内容填充页面。',
                  primaryAction: V3StateAction(
                    label: '重试',
                    onPressed: _load,
                    icon: Icons.refresh,
                  ),
                )
              : current == null
                  ? const V3StateSurface(
                      variant: V3StateSurfaceVariant.blocked,
                      title: '阶段当前不可用',
                      message: '这段阶段记录已经无法在当前账号下访问。',
                    )
                  : _ready(current),
    );
  }

  Widget _ready(V2LifeStage current) {
    final result = reasoning;
    final theme = Theme.of(context);
    final stageLabel = current.customLabel?.trim().isNotEmpty == true
        ? current.customLabel!
        : lifeStageLabels[current.kind] ?? '人生阶段';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (error != null) ...[
          V3SurfaceCard(
            color: theme.colorScheme.errorContainer,
            semanticLabel: error,
            child: Text(error!),
          ),
          const SizedBox(height: JiYiSpacing.sectionGap),
        ],
        if (status != null) ...[
          V3SurfaceCard(
            color: theme.colorScheme.primaryContainer,
            semanticLabel: status,
            child: Text(status!),
          ),
          const SizedBox(height: JiYiSpacing.sectionGap),
        ],
        V3SurfaceCard(
          key: const ValueKey('life-stage-identity'),
          color: theme.colorScheme.primaryContainer.withValues(alpha: .35),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  DecoratedBox(
                    decoration: BoxDecoration(
                      color: theme.colorScheme.primary,
                      borderRadius: BorderRadius.circular(JiYiRadius.control),
                    ),
                    child: const Padding(
                      padding: EdgeInsets.all(JiYiSpacing.sm),
                      child: Icon(Icons.timeline, color: Colors.white),
                    ),
                  ),
                  const SizedBox(width: JiYiSpacing.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          stageLabel,
                          style: theme.textTheme.labelLarge?.copyWith(
                            color: theme.colorScheme.primary,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: JiYiSpacing.xxs),
                        Text(
                          jiyiDisplayDateRange(current.startedAt, current.endedAt),
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: JiYiSpacing.md),
              Text(
                current.title,
                style: theme.textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              if (current.note != null && current.note!.trim().isNotEmpty) ...[
                const SizedBox(height: JiYiSpacing.sm),
                Text(current.note!),
              ],
              const SizedBox(height: JiYiSpacing.lg),
              Wrap(
                spacing: JiYiSpacing.sm,
                runSpacing: JiYiSpacing.xs,
                children: [
                  OutlinedButton.icon(
                    key: const ValueKey('life-stage-edit'),
                    onPressed: mutationFlight.isPending ? null : _edit,
                    icon: const Icon(Icons.edit_outlined),
                    label: const Text('编辑阶段'),
                  ),
                  TextButton.icon(
                    key: const ValueKey('life-stage-delete'),
                    onPressed: mutationFlight.isPending ? null : _delete,
                    icon: const Icon(Icons.delete_outline),
                    label: const Text('删除'),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: JiYiSpacing.lg),
        V3SectionHeader(
          title: '关联的人生经历',
          count: linkedEvents.length,
          subtitle: '只有你明确关联的事件会出现在这里。',
          trailing: OutlinedButton.icon(
            key: const ValueKey('life-stage-link-event'),
            onPressed: mutationFlight.isPending ? null : _linkEvent,
            icon: const Icon(Icons.add_link),
            label: const Text('关联经历'),
          ),
        ),
        const SizedBox(height: JiYiSpacing.sectionGap),
        if (linkedEvents.isEmpty)
          const V3StateSurface(
            variant: V3StateSurfaceVariant.empty,
            title: '还没有关联经历',
            message: '可以从已经保存的人生经历中，选择真正属于这段阶段的记录。',
          )
        else
          for (var index = 0; index < linkedEvents.length; index++) ...[
            _linkedEventCard(linkedEvents[index]),
            if (index != linkedEvents.length - 1)
              const SizedBox(height: JiYiSpacing.sm),
          ],
        const SizedBox(height: JiYiSpacing.lg),
        V3SurfaceCard(
          key: const ValueKey('life-stage-reasoning'),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const V3SectionHeader(
                title: '长期回顾',
                subtitle: '只在你主动提问后整理，并明确区分记录、推断和未知。',
              ),
              const SizedBox(height: JiYiSpacing.sm),
              TextField(
                key: const ValueKey('life-stage-reasoning-question'),
                controller: question,
                maxLength: 2000,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: '想回顾什么？',
                  hintText: '例如：这个阶段有哪些持续发生的变化？',
                ),
              ),
              FilledButton.icon(
                key: const ValueKey('life-stage-reasoning-submit'),
                onPressed: reasoningLoading ? null : _generateReasoning,
                icon: const Icon(Icons.auto_awesome),
                label: Text(reasoningLoading ? '正在整理…' : '生成回顾'),
              ),
              if (result != null) ...[
                const SizedBox(height: JiYiSpacing.md),
                V2TrustBadge(presentation: result.presentation),
                const SizedBox(height: JiYiSpacing.xs),
                Text(result.presentation.detail),
                if (result.presentation.state == AiPresentationState.inferred &&
                    result.answer != null) ...[
                  const SizedBox(height: JiYiSpacing.sm),
                  Text(result.answer!),
                ],
                for (var index = 0; index < result.citations.length; index++)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.fact_check_outlined),
                    title: Text('参考记录 ' + (index + 1).toString()),
                    subtitle: const Text('这条回顾基于你的相关记录。'),
                  ),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Widget _linkedEventCard(V2LifeStageEvent item) {
    final theme = Theme.of(context);
    return V3SurfaceCard(
      key: ValueKey('life-stage-linked-event-' + item.lifeEventId),
      semanticLabel: item.title + '，' + jiyiDisplayDate(item.startedAt) + '，已关联经历',
      padding: const EdgeInsets.all(JiYiSpacing.md),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.event_note_outlined, color: theme.colorScheme.primary),
          const SizedBox(width: JiYiSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(item.title, style: theme.textTheme.titleMedium),
                const SizedBox(height: JiYiSpacing.xxs),
                Text(
                  (lifeEventLabels[item.eventKind] ?? '人生经历') +
                      ' · ' +
                      jiyiDisplayDate(item.startedAt),
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          IconButton(
            key: ValueKey('life-stage-unlink-' + item.lifeEventId),
            tooltip: '取消关联',
            onPressed: mutationFlight.isPending ? null : () => _unlinkEvent(item),
            icon: const Icon(Icons.link_off),
          ),
        ],
      ),
    );
  }
}
