// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_format.dart';
import '../ui/jiyi_tokens.dart';
import '../ui/jiyi_v3_components.dart';
import 'life_editors.dart';
import 'life_event_detail_page.dart';
import 'life_models.dart';
import 'people_models.dart';
import 'v2_api.dart';
import 'v2_authority.dart';

class LifeEventsPage extends StatefulWidget {
  const LifeEventsPage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<LifeEventsPage> createState() => _LifeEventsPageState();
}

class _LifeEventsPageState extends State<LifeEventsPage> {
  late V2Api v2;
  JiYiApiClient? _boundApi;
  String? _boundOwner;
  int? _boundSessionVersion;
  final V2Authority readAuthority = V2Authority();
  final V2Authority mutationAuthority = V2Authority();
  final V2OperationFlight mutationFlight = V2OperationFlight();
  int _dialogGeneration = 0;

  List<V2LifeEvent> events = const [];
  List<V2PlacePickerItem> places = const [];
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
  void didUpdateWidget(LifeEventsPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api != widget.api) _rebindAndReload();
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
      _boundApi == widget.api &&
      _boundOwner == widget.api.authenticatedUserId &&
      _boundSessionVersion == widget.api.sessionVersion;

  void _rebindAndReload() {
    _dialogGeneration += 1;
    readAuthority.invalidate();
    mutationAuthority.invalidate();
    mutationFlight.invalidate();
    v2 = V2Api(widget.api);
    _rememberBinding();
    events = const [];
    places = const [];
    error = null;
    status = null;
    loading = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _load();
    });
  }

  void _checkAuthorityBinding() {
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
      snapshot = readAuthority.capture(widget.api, 'life-events:list');
    } catch (exc) {
      if (!context.mounted) return;
      setState(() {
        loading = false;
        error = exc.toString();
      });
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
        v2.listLifeEvents(limit: 100),
        v2.listPlaceChoices(limit: 100),
      ]);
      if (!_readCurrent(snapshot)) return;
      setState(() {
        events = result[0] as List<V2LifeEvent>;
        places = result[1] as List<V2PlacePickerItem>;
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
    LifeEventDraft? preserved;
    while (mounted) {
      if (!context.mounted) return;
      final dialogContext = context;
      final binding = (
        api: widget.api,
        owner: widget.api.authenticatedUserId,
        sessionVersion: widget.api.sessionVersion,
        generation: _dialogGeneration,
      );
      final draft = await showDialog<LifeEventDraft>(
        context: dialogContext,
        builder: (_) => LifeEventEditorDialog(
          places: places,
          initialDraft: preserved,
          initialError: preserved == null ? null : '保存失败，请检查网络后重试。',
        ),
      );
      if (draft == null || !_dialogStillCurrent(binding)) return;
      final operation = beginV2Operation(
        widget.api,
        mutationAuthority,
        mutationFlight,
        'life-event:create',
      );
      if (operation == null) return;
      try {
        final saved = await v2.createLifeEvent(
          kind: draft.kind,
          title: draft.title,
          customLabel: draft.customLabel,
          note: draft.note,
          startedAt: draft.startedAt,
          endedAt: draft.endedAt,
          placeId: draft.placeId,
        );
        if (!_mutationCurrent(operation)) return;
        setState(() => status = '已保存：' + saved.title);
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
    ({JiYiApiClient api, String? owner, int sessionVersion, int generation})
    binding,
  ) {
    return mounted &&
        identical(widget.api, binding.api) &&
        widget.api.authenticatedUserId == binding.owner &&
        widget.api.sessionVersion == binding.sessionVersion &&
        _dialogGeneration == binding.generation;
  }

  Future<void> _open(V2LifeEvent event) async {
    final owner = widget.api.authenticatedUserId;
    final version = widget.api.sessionVersion;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => LifeEventDetailPage(api: widget.api, eventId: event.id),
      ),
    );
    if (!mounted ||
        !_bindingMatches ||
        widget.api.authenticatedUserId != owner ||
        widget.api.sessionVersion != version) {
      return;
    }
    _load();
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
    _checkAuthorityBinding();
    return V3PageScaffold(
      topBar: V3TopBar(
        title: '人生经历',
        subtitle: '把真实发生过的节点整理成一条可回看的线索',
        onBack: () => Navigator.of(context).maybePop(),
        leading: Semantics(
          button: true,
          label: '返回',
          onTap: () => Navigator.of(context).maybePop(),
          child: ExcludeSemantics(
            child: IconButton(
              onPressed: () => Navigator.of(context).maybePop(),
              tooltip: 'Back',
              icon: const Icon(Icons.arrow_back_ios_new),
              constraints: const BoxConstraints(
                minWidth: JiYiTapTarget.normal,
                minHeight: JiYiTapTarget.normal,
              ),
            ),
          ),
        ),
        trailing: OutlinedButton.icon(
          key: const ValueKey('life-event-create'),
          onPressed: mutationFlight.isPending ? null : _create,
          icon: const Icon(Icons.add),
          label: const Text('新建经历'),
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
            title: '人生经历',
            count: loading ? null : events.length,
            subtitle: '时间、地点和备注都来自你明确保存的记录。',
          ),
          const SizedBox(height: JiYiSpacing.sectionGap),
          if (loading)
            const V3StateSurface(
              variant: V3StateSurfaceVariant.loading,
              title: '正在读取人生经历',
              message: '正在从你的记录中整理时间线。',
            )
          else if (error != null)
            V3StateSurface(
              variant: _errorVariant(),
              title: '暂时无法读取人生经历',
              message: '请稍后重试；当前不会用猜测内容填充页面。',
              primaryAction: V3StateAction(
                label: '重试',
                onPressed: _load,
                icon: Icons.refresh,
              ),
            )
          else if (events.isEmpty)
            V3StateSurface(
              variant: V3StateSurfaceVariant.empty,
              title: '还没有已保存的人生经历',
              message: '从一个你愿意记住的真实节点开始。',
              primaryAction: V3StateAction(
                label: '新建经历',
                onPressed: _create,
                icon: Icons.add,
              ),
            )
          else
            _eventTimeline(),
        ],
      ),
    );
  }

  Widget _eventTimeline() {
    return Column(
      children: [
        for (var index = 0; index < events.length; index++) ...[
          _eventCard(events[index], isLast: index == events.length - 1),
          if (index != events.length - 1)
            const SizedBox(height: JiYiSpacing.sm),
        ],
      ],
    );
  }

  Widget _eventCard(V2LifeEvent event, {required bool isLast}) {
    final place = event.placeId == null
        ? null
        : places
              .where(
                (item) => item.id.toLowerCase() == event.placeId!.toLowerCase(),
              )
              .map((item) => item.name)
              .firstOrNull;
    final meta = <String>[
      lifeEventLabels[event.kind] ?? event.customLabel ?? '人生经历',
      jiyiDisplayDateRange(event.startedAt, event.endedAt),
      if (place != null) place,
    ];
    final theme = Theme.of(context);
    return V3SurfaceCard(
      key: ValueKey('life-event-${event.id}'),
      onTap: () => _open(event),
      semanticLabel: '${event.title}，${meta.join('，')}，打开详情',
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
                  child: Icon(
                    _eventIcon(event.kind),
                    color: theme.colorScheme.primary,
                  ),
                ),
              ),
              if (!isLast)
                Container(
                  width: 2,
                  height: 54,
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
                  event.title,
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.xxs),
                Text(
                  meta.join(' · '),
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                if (event.note != null && event.note!.trim().isNotEmpty) ...[
                  const SizedBox(height: JiYiSpacing.sm),
                  Text(
                    event.note!,
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

  IconData _eventIcon(String kind) => switch (kind) {
    'TRAVEL' => Icons.map_outlined,
    'MEDICAL' => Icons.local_hospital_outlined,
    'GATHERING' => Icons.groups_outlined,
    'WORK' => Icons.work_outline,
    'EDUCATION' => Icons.school_outlined,
    'FAMILY' => Icons.home_outlined,
    _ => Icons.event_note_outlined,
  };
}

extension _LifeEventFirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
