// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../ai_inference_presentation.dart';
import '../api_client.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';
import 'life_editors.dart';
import 'life_models.dart';
import 'v2_api.dart';
import 'v2_authority.dart';
import 'v2_widgets.dart';

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
  late final V2Api v2 = V2Api(widget.api);
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
    _load();
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

  bool _reasoningCurrent(V2OperationContext operation) =>
      mounted &&
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
    final identity = 'life-stage:' + widget.stageId;
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = readAuthority.capture(widget.api, identity);
    } catch (exc) {
      if (mounted) setState(() { loading = false; error = exc.toString(); });
      return;
    }
    setState(() { loading = true; error = null; });
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
    final draft = await showDialog<LifeStageDraft>(
      context: context,
      builder: (_) => LifeStageEditorDialog(initial: current),
    );
    if (draft == null || !mounted) return;
    await _runMutation('life-stage:update:' + current.id, () async {
      final saved = await v2.updateLifeStage(
        current,
        kind: draft.kind,
        title: draft.title,
        customLabel: draft.customLabel,
        note: draft.note,
        startedAt: draft.startedAt,
        endedAt: draft.endedAt,
      );
      return '阶段已更新：' + saved.title;
    });
  }

  Future<void> _delete() async {
    final current = stage;
    if (current == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('删除人生阶段？'),
        content: Text('将删除“' + current.title + '”及其事件关联。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('删除')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await _runMutation(
      'life-stage:delete:' + current.id,
      () async {
        await v2.deleteLifeStage(current.id);
        if (mounted) Navigator.of(context).pop();
        return null;
      },
      refresh: false,
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
            title: const Text('关联人生事件'),
            content: DropdownButtonFormField<String>(
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
              TextButton(onPressed: () => Navigator.pop(context), child: const Text('取消')),
              FilledButton(onPressed: () => Navigator.pop(context, value), child: const Text('关联')),
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
        return '人生事件已关联';
      },
    );
  }

  Future<void> _unlinkEvent(V2LifeStageEvent item) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('取消事件关联？'),
        content: const Text('只删除阶段与事件之间的显式关系。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('取消关联')),
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

  @override
  Widget build(BuildContext context) {
    final current = stage;
    return Scaffold(
      appBar: AppBar(title: Text(current?.title ?? '人生阶段')),
      body: SafeArea(
        child: JiYiPageFrame(
          title: current?.title ?? '人生阶段',
          subtitle: '阶段和事件关系是明确记录；长期回顾是用户主动触发的 AI 生成面。',
          child: loading
              ? const Center(child: CircularProgressIndicator())
              : error != null && current == null
                  ? V2ErrorState(message: error!, onRetry: _load)
                  : current == null
                      ? const Text('阶段当前不可用')
                      : _ready(current),
        ),
      ),
    );
  }

  Widget _ready(V2LifeStage current) {
    final result = reasoning;
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
          title: '阶段详情',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              V2KeyValue(label: '类型', value: lifeStageLabels[current.kind] ?? current.kind),
              V2KeyValue(label: '开始', value: current.startedAt),
              V2KeyValue(label: '结束', value: current.endedAt ?? '开放'),
              V2KeyValue(label: '备注', value: current.note ?? '无'),
              Wrap(
                spacing: JiYiSpacing.sm,
                children: [
                  OutlinedButton(onPressed: mutationFlight.isPending ? null : _edit, child: const Text('编辑')),
                  TextButton(onPressed: mutationFlight.isPending ? null : _delete, child: const Text('删除')),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: JiYiSpacing.md),
        JiYiSectionCard(
          title: '关联事件',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              OutlinedButton.icon(
                onPressed: mutationFlight.isPending ? null : _linkEvent,
                icon: const Icon(Icons.add_link),
                label: const Text('关联已有事件'),
              ),
              if (linkedEvents.isEmpty)
                const Padding(
                  padding: EdgeInsets.only(top: JiYiSpacing.sm),
                  child: Text('尚未关联人生事件。'),
                ),
              for (final item in linkedEvents)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(item.title),
                  subtitle: Text(item.eventKind + ' · ' + item.startedAt),
                  trailing: IconButton(
                    tooltip: '取消关联',
                    onPressed: mutationFlight.isPending ? null : () => _unlinkEvent(item),
                    icon: const Icon(Icons.link_off),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: JiYiSpacing.md),
        JiYiSectionCard(
          title: '长期回顾',
          subtitle: '只有点击生成后才调用 AI；引用保留 canonical evidence identity。',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(
                controller: question,
                maxLength: 2000,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: '要回顾的问题',
                  hintText: '例如：这个阶段有哪些持续发生的工作变化？',
                ),
              ),
              FilledButton.icon(
                onPressed: reasoningLoading ? null : _generateReasoning,
                icon: const Icon(Icons.auto_awesome),
                label: Text(reasoningLoading ? '正在整理…' : '生成证据回顾'),
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
                for (final citation in result.citations)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.fact_check_outlined),
                    title: Text(citation.slot + ' · ' + citation.kind),
                    subtitle: Text(
                      (citation.memoryTrustState ?? '明确实体引用') +
                          (citation.memoryId == null
                              ? ''
                              : ' · Memory ' + citation.memoryId!),
                    ),
                  ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}
