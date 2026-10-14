// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_format.dart';
import '../ui/jiyi_tokens.dart';
import '../ui/jiyi_v3_components.dart';
import 'life_editors.dart';
import 'life_models.dart';
import 'life_stage_detail_page.dart';
import 'v2_api.dart';
import 'v2_authority.dart';

class LifeStagesPage extends StatefulWidget {
  const LifeStagesPage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<LifeStagesPage> createState() => _LifeStagesPageState();
}

class _LifeStagesPageState extends State<LifeStagesPage> {
  late V2Api v2;
  JiYiApiClient? _boundApi;
  String? _boundOwner;
  int? _boundSessionVersion;
  final V2Authority readAuthority = V2Authority();
  final V2Authority mutationAuthority = V2Authority();
  final V2OperationFlight mutationFlight = V2OperationFlight();
  int _dialogGeneration = 0;
  bool _dialogInFlight = false;
  bool _navigationInFlight = false;

  List<V2LifeStage> stages = const [];
  bool loading = true;
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
  void didUpdateWidget(LifeStagesPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.api, widget.api)) _rebindAndReload();
  }

  @override
  void dispose() {
    readAuthority.invalidate();
    mutationAuthority.invalidate();
    mutationFlight.invalidate();
    super.dispose();
  }

  void _rememberBinding() {
    _boundApi = widget.api;
    _boundOwner = widget.api.authenticatedUserId;
    _boundSessionVersion = widget.api.sessionVersion;
  }

  bool get _bindingMatches =>
      identical(_boundApi, widget.api) &&
      _boundOwner == widget.api.authenticatedUserId &&
      _boundSessionVersion == widget.api.sessionVersion;

  void _rebindAndReload() {
    _dialogGeneration += 1;
    readAuthority.invalidate();
    mutationAuthority.invalidate();
    mutationFlight.invalidate();
    v2 = V2Api(widget.api);
    _rememberBinding();
    stages = const [];
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

  Future<void> _load() async {
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = readAuthority.capture(widget.api, 'life-stages:list');
    } catch (exc) {
      if (mounted)
        setState(() {
          loading = false;
          error = exc.toString();
        });
      return;
    }
    if (mounted)
      setState(() {
        loading = true;
        error = null;
      });
    try {
      final result = await v2.listLifeStages(limit: 100);
      if (!_readCurrent(snapshot)) return;
      setState(() {
        stages = result;
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

  Future<void> _create() async {
    if (_dialogInFlight || _navigationInFlight) return;
    setState(() => _dialogInFlight = true);
    LifeStageDraft? preserved;
    try {
      while (mounted) {
        final binding = (
          api: widget.api,
          owner: widget.api.authenticatedUserId,
          sessionVersion: widget.api.sessionVersion,
          generation: _dialogGeneration,
        );
        if (!mounted) return;
        final draft = await showDialog<LifeStageDraft>(
          context: context,
          builder: (_) => LifeStageEditorDialog(
            initialDraft: preserved,
            initialError: preserved == null ? null : '保存失败，请检查网络后重试。',
          ),
        );
        if (draft == null || !_dialogStillCurrent(binding)) return;
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
          setState(() => status = '已保存阶段：' + saved.title);
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
    } finally {
      if (mounted) {
        setState(() => _dialogInFlight = false);
      } else {
        _dialogInFlight = false;
      }
    }
  }

  bool _dialogStillCurrent(
    ({JiYiApiClient api, String? owner, int sessionVersion, int generation})
    binding,
  ) {
    return mounted &&
        identical(widget.api, binding.api) &&
        widget.api.authenticatedUserId == binding.owner &&
        widget.api.sessionVersion == binding.sessionVersion &&
        _dialogGeneration == binding.generation;
  }

  Future<void> _open(V2LifeStage stage) async {
    if (_navigationInFlight || _dialogInFlight) return;
    final owner = widget.api.authenticatedUserId;
    final sessionVersion = widget.api.sessionVersion;
    setState(() => _navigationInFlight = true);
    try {
      await Navigator.of(context).push<void>(
        MaterialPageRoute(
          builder: (_) =>
              LifeStageDetailPage(api: widget.api, stageId: stage.id),
        ),
      );
      if (!mounted ||
          !_bindingMatches ||
          widget.api.authenticatedUserId != owner ||
          widget.api.sessionVersion != sessionVersion) {
        return;
      }
      _load();
    } finally {
      if (mounted) {
        setState(() => _navigationInFlight = false);
      } else {
        _navigationInFlight = false;
      }
    }
  }

  V3StateSurfaceVariant _errorVariant() {
    final value = error ?? '';
    if (value.contains('网络') ||
        value.contains('连接') ||
        value.contains('Transport')) {
      return V3StateSurfaceVariant.offline;
    }
    if (value.contains('401') ||
        value.contains('403') ||
        value.contains('权限')) {
      return V3StateSurfaceVariant.blocked;
    }
    return V3StateSurfaceVariant.error;
  }

  @override
  Widget build(BuildContext context) {
    _checkBinding();
    return V3PageScaffold(
      topBar: V3TopBar(
        title: '人生阶段',
        subtitle: '把一段时光放在一起，慢慢看见它的脉络',
        onBack: () => Navigator.of(context).maybePop(),
        trailing: OutlinedButton.icon(
          key: const ValueKey('life-stages-create'),
          onPressed:
              mutationFlight.isPending || _dialogInFlight || _navigationInFlight
              ? null
              : _create,
          icon: const Icon(Icons.add),
          label: const Text('新建阶段'),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (status != null) ...[
            V3SurfaceCard(
              color: Theme.of(context).colorScheme.primaryContainer,
              semanticLabel: status,
              child: Text(status!),
            ),
            const SizedBox(height: JiYiSpacing.sectionGap),
          ],
          V3SectionHeader(
            title: '人生阶段',
            count: loading ? null : stages.length,
            subtitle: '阶段由你明确记录，事件只通过显式关联加入。',
          ),
          const SizedBox(height: JiYiSpacing.sectionGap),
          if (loading)
            const V3StateSurface(
              variant: V3StateSurfaceVariant.loading,
              title: '正在读取人生阶段',
              message: '正在从你的记录中整理时间脉络。',
            )
          else if (error != null)
            V3StateSurface(
              variant: _errorVariant(),
              title: '暂时无法读取人生阶段',
              message: '请稍后重试；当前不会用猜测内容填充页面。',
              primaryAction: V3StateAction(
                label: '重试',
                onPressed: _load,
                icon: Icons.refresh,
              ),
            )
          else if (stages.isEmpty)
            V3StateSurface(
              variant: V3StateSurfaceVariant.empty,
              title: '还没有已保存的人生阶段',
              message: '从一段你愿意记住的工作、学习、家庭或居住时光开始。',
              primaryAction: V3StateAction(
                label: '新建阶段',
                onPressed: _create,
                icon: Icons.add,
              ),
            )
          else
            _stageTimeline(),
        ],
      ),
    );
  }

  Widget _stageTimeline() {
    return Column(
      children: [
        for (var index = 0; index < stages.length; index++) ...[
          _stageCard(stages[index], isLast: index == stages.length - 1),
          if (index != stages.length - 1)
            const SizedBox(height: JiYiSpacing.sm),
        ],
      ],
    );
  }

  Widget _stageCard(V2LifeStage stage, {required bool isLast}) {
    final theme = Theme.of(context);
    final label = stage.customLabel?.trim().isNotEmpty == true
        ? stage.customLabel!
        : lifeStageLabels[stage.kind] ?? '人生阶段';
    final date = jiyiDisplayDateRange(stage.startedAt, stage.endedAt);
    return V3SurfaceCard(
      key: ValueKey('life-stage-card-${stage.id}'),
      onTap: () => _open(stage),
      semanticLabel: '${stage.title}，$label，$date，打开阶段详情',
      padding: const EdgeInsets.fromLTRB(
        JiYiSpacing.cardPadding,
        JiYiSpacing.cardPadding,
        JiYiSpacing.sm,
        JiYiSpacing.cardPadding,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Column(
            children: [
              DecoratedBox(
                decoration: BoxDecoration(
                  color: theme.colorScheme.primaryContainer,
                  shape: BoxShape.circle,
                ),
                child: Padding(
                  padding: const EdgeInsets.all(JiYiSpacing.sm),
                  child: Icon(Icons.timeline, color: theme.colorScheme.primary),
                ),
              ),
              if (!isLast)
                Container(
                  width: 2,
                  height: 56,
                  margin: const EdgeInsets.only(top: JiYiSpacing.xs),
                  color: theme.colorScheme.primary.withValues(alpha: .18),
                ),
            ],
          ),
          const SizedBox(width: JiYiSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  stage.title,
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.xxs),
                Text(
                  '$label · $date',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                if (stage.note != null && stage.note!.trim().isNotEmpty) ...[
                  const SizedBox(height: JiYiSpacing.sm),
                  Text(
                    stage.note!,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ],
            ),
          ),
          const Icon(Icons.chevron_right),
        ],
      ),
    );
  }
}
