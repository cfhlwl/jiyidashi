// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';
import 'life_editors.dart';
import 'life_models.dart';
import 'life_stage_detail_page.dart';
import 'v2_api.dart';
import 'v2_authority.dart';
import 'v2_widgets.dart';

class LifeStagesPage extends StatefulWidget {
  const LifeStagesPage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<LifeStagesPage> createState() => _LifeStagesPageState();
}

class _LifeStagesPageState extends State<LifeStagesPage> {
  late final V2Api v2 = V2Api(widget.api);
  final V2Authority readAuthority = V2Authority();
  final V2Authority mutationAuthority = V2Authority();
  final V2OperationFlight mutationFlight = V2OperationFlight();

  List<V2LifeStage> stages = const [];
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

  bool _mutationCurrent(V2OperationContext operation) =>
      mounted &&
      mutationAuthority.isCurrent(
        widget.api,
        operation.snapshot,
        operation.snapshot.identity,
      ) &&
      mutationFlight.isCurrent(operation.token, widget.api);

  Future<void> _load() async {
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = readAuthority.capture(widget.api, 'life-stages:list');
    } catch (exc) {
      if (mounted) setState(() { loading = false; error = exc.toString(); });
      return;
    }
    setState(() { loading = true; error = null; });
    try {
      final result = await v2.listLifeStages(limit: 100);
      if (!_readCurrent(snapshot)) return;
      setState(() { stages = result; loading = false; });
    } catch (exc) {
      if (!_readCurrent(snapshot)) return;
      setState(() { loading = false; error = exc.toString(); });
    }
  }

  Future<void> _create() async {
    final draft = await showDialog<LifeStageDraft>(
      context: context,
      builder: (_) => const LifeStageEditorDialog(),
    );
    if (draft == null || !mounted) return;
    final operation = beginV2Operation(
      widget.api,
      mutationAuthority,
      mutationFlight,
      'life-stage:create',
    );
    if (operation == null) return;
    try {
      final saved = await v2.createLifeStage(
        kind: draft.kind,
        title: draft.title,
        customLabel: draft.customLabel,
        note: draft.note,
        startedAt: draft.startedAt,
        endedAt: draft.endedAt,
      );
      if (!_mutationCurrent(operation)) return;
      setState(() => status = '已创建阶段：' + saved.title);
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
      if (mutationFlight.end(operation.token) && mounted) setState(() {});
    }
  }

  Future<void> _open(V2LifeStage stage) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => LifeStageDetailPage(api: widget.api, stageId: stage.id),
      ),
    );
    if (mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('人生阶段')),
      body: SafeArea(
        child: JiYiPageFrame(
          title: '人生阶段',
          subtitle: '阶段可以保持开放；事件只通过显式关系加入，不按标题或时间自动匹配。',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              FilledButton.icon(
                onPressed: mutationFlight.isPending ? null : _create,
                icon: const Icon(Icons.add),
                label: const Text('新建人生阶段'),
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
              else if (stages.isEmpty)
                const JiYiEmptyState(
                  icon: Icons.view_timeline_outlined,
                  title: '还没有人生阶段',
                  message: '可以从一段工作、学习、家庭或居住阶段开始。',
                )
              else
                V2SectionCard(
                  title: '阶段列表',
                  child: Column(
                    children: [
                      for (final stage in stages)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          title: Text(stage.title),
                          subtitle: Text(
                            (lifeStageLabels[stage.kind] ?? stage.kind) +
                                ' · ' +
                                stage.startedAt +
                                ' → ' +
                                (stage.endedAt ?? '开放'),
                          ),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () => _open(stage),
                        ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
