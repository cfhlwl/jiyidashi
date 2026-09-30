// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';
import 'life_editors.dart';
import 'life_event_detail_page.dart';
import 'life_models.dart';
import 'people_models.dart';
import 'v2_api.dart';
import 'v2_authority.dart';
import 'v2_widgets.dart';

class LifeEventsPage extends StatefulWidget {
  const LifeEventsPage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<LifeEventsPage> createState() => _LifeEventsPageState();
}

class _LifeEventsPageState extends State<LifeEventsPage> {
  late final V2Api v2 = V2Api(widget.api);
  final V2Authority readAuthority = V2Authority();
  final V2Authority mutationAuthority = V2Authority();
  final V2OperationFlight mutationFlight = V2OperationFlight();

  List<V2LifeEvent> events = const [];
  List<V2PlacePickerItem> places = const [];
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
      snapshot = readAuthority.capture(widget.api, 'life-events:list');
    } catch (exc) {
      if (mounted) setState(() { loading = false; error = exc.toString(); });
      return;
    }
    setState(() { loading = true; error = null; });
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
      setState(() { loading = false; error = exc.toString(); });
    }
  }

  Future<void> _create() async {
    final draft = await showDialog<LifeEventDraft>(
      context: context,
      builder: (_) => LifeEventEditorDialog(places: places),
    );
    if (draft == null || !mounted) return;
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
      setState(() => status = '已创建事件：' + saved.title);
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

  Future<void> _open(V2LifeEvent event) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => LifeEventDetailPage(api: widget.api, eventId: event.id),
      ),
    );
    if (mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('人生事件')),
      body: SafeArea(
        child: JiYiPageFrame(
          title: '人生事件',
          subtitle: '这些经历来自你的明确记录；地点和相关记忆都从已有内容中选择。',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              FilledButton.icon(
                onPressed: mutationFlight.isPending ? null : _create,
                icon: const Icon(Icons.add),
                label: const Text('新建人生事件'),
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
              else if (events.isEmpty)
                const JiYiEmptyState(
                  icon: Icons.event_note_outlined,
                  title: '还没有人生事件',
                  message: '可以从一个明确发生过的事件开始记录。',
                )
              else
                V2SectionCard(
                  title: '事件列表',
                  child: Column(
                    children: [
                      for (final event in events)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          title: Text(event.title),
                          subtitle: Text(
                            (lifeEventLabels[event.kind] ?? '其他经历') +
                                ' · ' +
                                event.startedAt,
                          ),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () => _open(event),
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
