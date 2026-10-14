// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_format.dart';
import '../ui/jiyi_tokens.dart';
import '../ui/jiyi_v3_components.dart';
import 'life_editors.dart';
import 'life_models.dart';
import 'people_models.dart';
import 'v2_api.dart';
import 'v2_authority.dart';
import 'v2_widgets.dart';

class LifeEventDetailPage extends StatefulWidget {
  const LifeEventDetailPage({
    super.key,
    required this.api,
    required this.eventId,
  });

  final JiYiApiClient api;
  final String eventId;

  @override
  State<LifeEventDetailPage> createState() => _LifeEventDetailPageState();
}

class _LifeEventDetailPageState extends State<LifeEventDetailPage> {
  late V2Api v2;
  JiYiApiClient? _boundApi;
  String? _boundOwner;
  int? _boundSessionVersion;
  final V2Authority readAuthority = V2Authority();
  final V2Authority mutationAuthority = V2Authority();
  final V2OperationFlight mutationFlight = V2OperationFlight();

  V2LifeEvent? event;
  List<V2LifeEventMemoryEvidence> evidence = const [];
  List<V2MemoryPickerItem> memories = const [];
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
  void didUpdateWidget(LifeEventDetailPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api != widget.api || oldWidget.eventId != widget.eventId) {
      _rebindAndReload();
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

  void _rememberBinding() {
    _boundApi = widget.api;
    _boundOwner = widget.api.authenticatedUserId;
    _boundSessionVersion = widget.api.sessionVersion;
  }

  bool get _bindingMatches =>
      _boundApi == widget.api &&
      _boundOwner == widget.api.authenticatedUserId &&
      _boundSessionVersion == widget.api.sessionVersion;

  void _clear() {
    event = null;
    evidence = const [];
    memories = const [];
    places = const [];
    loading = true;
    error = null;
    status = null;
  }

  void _rebindAndReload() {
    readAuthority.invalidate();
    mutationAuthority.invalidate();
    mutationFlight.invalidate();
    v2 = V2Api(widget.api);
    _rememberBinding();
    _clear();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _load();
    });
  }

  void _checkAuthorityBinding() {
    if (!_bindingMatches) _rebindAndReload();
  }

  Future<void> _load() async {
    final identity = 'life-event:' + widget.eventId;
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
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final result = await Future.wait<Object>([
        v2.getLifeEvent(widget.eventId),
        v2.listLifeEventMemories(widget.eventId, limit: 100),
        v2.listMemoryChoices(limit: 100),
        v2.listPlaceChoices(limit: 100),
      ]);
      if (!_readCurrent(snapshot)) return;
      setState(() {
        event = result[0] as V2LifeEvent;
        evidence = result[1] as List<V2LifeEventMemoryEvidence>;
        memories = result[2] as List<V2MemoryPickerItem>;
        places = result[3] as List<V2PlacePickerItem>;
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

  Future<void> _runMutation(
    String identity,
    Future<String?> Function() action, {
    bool refresh = true,
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
      if (message != null) setState(() => status = message);
      if (onSuccess != null) onSuccess();
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
    final current = event;
    if (current == null) return;
    LifeEventDraft? preserved;
    while (mounted && _bindingMatches) {
      if (!context.mounted) return;
      final dialogContext = context;
      final draft = await showDialog<LifeEventDraft>(
        context: dialogContext,
        builder: (_) => LifeEventEditorDialog(
          places: places,
          initial: preserved == null ? current : null,
          initialDraft: preserved,
          initialError: preserved == null ? null : '保存失败，请检查网络后重试。',
        ),
      );
      if (draft == null || !mounted || !_bindingMatches) return;
      final operation = beginV2Operation(
        widget.api,
        mutationAuthority,
        mutationFlight,
        'life-event:update:' + current.id,
      );
      if (operation == null) return;
      try {
        final saved = await v2.updateLifeEvent(
          current,
          kind: draft.kind,
          title: draft.title,
          customLabel: draft.customLabel,
          note: draft.note,
          startedAt: draft.startedAt,
          endedAt: draft.endedAt,
          placeId: draft.placeId,
        );
        if (!_mutationCurrent(operation)) return;
        setState(() => status = '事件已更新：' + saved.title);
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

  Future<void> _delete() async {
    final current = event;
    if (current == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('删除人生事件？'),
        content: Text('将删除“' + current.title + '”及其显式关联关系。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await _runMutation(
      'life-event:delete:' + current.id,
      () async {
        await v2.deleteLifeEvent(current.id);
        return null;
      },
      refresh: false,
      onSuccess: () {
        if (mounted) Navigator.of(context).pop();
      },
    );
  }

  Future<void> _linkMemory() async {
    final linked = evidence.map((item) => item.memoryId.toLowerCase()).toSet();
    final choices = memories
        .where((item) => !linked.contains(item.id.toLowerCase()))
        .toList(growable: false);
    if (choices.isEmpty) {
      setState(() => status = '没有可继续关联的记忆');
      return;
    }
    final selected = await showDialog<String>(
      context: context,
      builder: (context) {
        String value = choices.first.id;
        return StatefulBuilder(
          builder: (context, setLocal) => AlertDialog(
            title: const Text('关联相关记录'),
            content: DropdownButtonFormField<String>(
              initialValue: value,
              items: [
                for (final item in choices)
                  DropdownMenuItem(
                    value: item.id,
                    child: Text(item.title ?? item.content),
                  ),
              ],
              onChanged: (next) {
                if (next != null) setLocal(() => value = next);
              },
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('取消'),
              ),
              FilledButton(
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
      'life-event:link:' + widget.eventId + ':' + selected,
      () async {
        await v2.linkLifeEventMemory(
          eventId: widget.eventId,
          memoryId: selected,
        );
        return '相关记录已关联';
      },
    );
  }

  Future<void> _unlink(V2LifeEventMemoryEvidence item) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('取消相关记录关联？'),
        content: const Text('只取消这段经历与相关记录的关联，不会删除原记录。'),
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
    await _runMutation('life-event:unlink:' + item.linkId, () async {
      await v2.unlinkLifeEventMemory(
        eventId: widget.eventId,
        memoryId: item.memoryId,
      );
      return '相关记录关联已取消';
    });
  }

  @override
  Widget build(BuildContext context) {
    _checkAuthorityBinding();
    final current = event;
    return V3PageScaffold(
      topBar: V3TopBar(
        title: current?.title ?? '人生经历',
        subtitle: '只展示你明确保存的内容和关联记录',
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
      ),
      child: loading
          ? const V3StateSurface(
              variant: V3StateSurfaceVariant.loading,
              title: '正在读取这段经历',
              message: '正在验证事件、地点和相关记录。',
            )
          : error != null && current == null
          ? V3StateSurface(
              variant: _errorVariant(),
              title: '这段经历暂时不可用',
              message: '当前没有可靠的内容可以展示。',
              primaryAction: V3StateAction(
                label: '重试',
                onPressed: _load,
                icon: Icons.refresh,
              ),
            )
          : current == null
          ? const V3StateSurface(
              variant: V3StateSurfaceVariant.empty,
              title: '这段经历不存在',
              message: '它可能已被删除，或当前账号没有访问权限。',
            )
          : _ready(current),
    );
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

  Widget _ready(V2LifeEvent current) {
    final placeName = current.placeId == null
        ? '未关联'
        : places
                  .where(
                    (item) =>
                        item.id.toLowerCase() == current.placeId!.toLowerCase(),
                  )
                  .map((item) => item.name)
                  .cast<String?>()
                  .firstOrNull ??
              '已关联地点';
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
        V3SurfaceCard(
          semanticLabel: '经历详情：${current.title}',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                current.title,
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              if (current.note != null && current.note!.trim().isNotEmpty) ...[
                const SizedBox(height: JiYiSpacing.sm),
                Text(current.note!),
              ],
              const SizedBox(height: JiYiSpacing.md),
              V2KeyValue(
                label: '类型',
                value: lifeEventLabels[current.kind] ?? '其他经历',
              ),
              V2KeyValue(
                label: '开始',
                value: jiyiDisplayDateTime(current.startedAt),
              ),
              V2KeyValue(
                label: '结束',
                value: current.endedAt == null
                    ? '未设置'
                    : jiyiDisplayDateTime(current.endedAt!),
              ),
              V2KeyValue(label: '地点', value: placeName),
              V2KeyValue(label: '备注', value: current.note ?? '无'),
              Wrap(
                spacing: JiYiSpacing.sm,
                children: [
                  OutlinedButton(
                    key: const ValueKey('life-event-edit'),
                    onPressed: mutationFlight.isPending ? null : _edit,
                    child: const Text('编辑'),
                  ),
                  TextButton(
                    key: const ValueKey('life-event-delete'),
                    onPressed: mutationFlight.isPending ? null : _delete,
                    child: const Text('删除'),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: JiYiSpacing.md),
        V3SurfaceCard(
          semanticLabel: '相关记录',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const V3SectionHeader(title: '相关记录', subtitle: '只显示真实关联的记忆记录。'),
              const SizedBox(height: JiYiSpacing.sm),
              OutlinedButton.icon(
                key: const ValueKey('life-event-link-memory'),
                onPressed: mutationFlight.isPending ? null : _linkMemory,
                icon: const Icon(Icons.add_link),
                label: const Text('关联已有记录'),
              ),
              if (evidence.isEmpty)
                const Padding(
                  padding: EdgeInsets.only(top: JiYiSpacing.sm),
                  child: Text('还没有关联相关记录。'),
                ),
              for (final item in evidence)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(item.title ?? item.content),
                  subtitle: Text(
                    '记录时间：' + jiyiDisplayDateTime(item.occurredAt),
                  ),
                  trailing: IconButton(
                    tooltip: '取消关联',
                    onPressed: mutationFlight.isPending
                        ? null
                        : () => _unlink(item),
                    icon: const Icon(Icons.link_off),
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
