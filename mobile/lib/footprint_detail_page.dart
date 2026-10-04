import 'package:flutter/material.dart';

import 'amap_footprint_map.dart';
import 'api_client.dart';
import 'footprint_models.dart';
import 'place_detail_page.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_format.dart';
import 'ui/jiyi_tokens.dart';

class FootprintDetailPage extends StatefulWidget {
  const FootprintDetailPage({
    super.key,
    required this.api,
    required this.footprint,
    required this.mapPrivacyAccepted,
    this.onAcceptMapPrivacy,
  });

  final JiYiApiClient api;
  final FootprintDay footprint;
  final bool mapPrivacyAccepted;
  final Future<void> Function()? onAcceptMapPrivacy;

  @override
  State<FootprintDetailPage> createState() => _FootprintDetailPageState();
}

class _FootprintDetailPageState extends State<FootprintDetailPage> {
  int _selectedIndex = 0;
  late bool _privacyAccepted;

  @override
  void initState() {
    super.initState();
    _privacyAccepted = widget.mapPrivacyAccepted;
  }

  Future<void> _acceptPrivacy() async {
    final action = widget.onAcceptMapPrivacy;
    if (action == null) return;
    await action();
    if (mounted) {
      setState(() => _privacyAccepted = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final visits = widget.footprint.visits;
    final mappable = widget.footprint.mappableVisits;
    final selected = mappable.isEmpty
        ? null
        : mappable[_selectedIndex.clamp(0, mappable.length - 1)];

    return Scaffold(
      appBar: AppBar(title: const Text('今日足迹')),
      body: SafeArea(
        child: JiYiPageFrame(
          title: '今天去了哪里',
          subtitle: jiyiDisplayDate(widget.footprint.day),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              JiYiFootprintMap(
                visits: visits,
                privacyAccepted: _privacyAccepted,
                selectedIndex: _selectedIndex,
                onSelected: (index) {
                  if (mounted) setState(() => _selectedIndex = index);
                },
              ),
              if (!_privacyAccepted && widget.onAcceptMapPrivacy != null) ...[
                const SizedBox(height: JiYiSpacing.sm),
                OutlinedButton.icon(
                  key: const ValueKey('amap-privacy-accept'),
                  onPressed: _acceptPrivacy,
                  icon: const Icon(Icons.map_outlined),
                  label: const Text('同意地图服务隐私说明并启用地图'),
                ),
              ],
              if (mappable.length > 1) ...[
                const SizedBox(height: JiYiSpacing.sm),
                const JiYiStatusBanner(
                  kind: JiYiStatusKind.info,
                  title: '地点间连线表示到访顺序',
                  message: '当前没有原始 GPS 轨迹投影，因此连线不代表你实际步行、驾车或乘车的精确路线。',
                ),
              ],
              if (selected != null) ...[
                const SizedBox(height: JiYiSpacing.md),
                JiYiSectionCard(
                  key: ValueKey('footprint-selected-${selected.id}'),
                  leading: Icon(
                    selected.finalized
                        ? Icons.location_on_outlined
                        : Icons.my_location_outlined,
                    color: Theme.of(context).colorScheme.primary,
                  ),
                  title: selected.placeName,
                  subtitle: _visitTime(selected),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (selected.address != null) Text(selected.address!),
                      const SizedBox(height: JiYiSpacing.sm),
                      Text(selected.finalized ? '已形成足迹' : '仍在更新'),
                      if (_visitDuration(selected) != null) ...[
                        const SizedBox(height: JiYiSpacing.xs),
                        Text('停留 ${_visitDuration(selected)!}'),
                      ],
                      const SizedBox(height: JiYiSpacing.sm),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: TextButton.icon(
                          onPressed: () {
                            Navigator.of(context).push<void>(
                              MaterialPageRoute<void>(
                                builder: (_) => PlaceDetailPage(
                                  api: widget.api,
                                  placeId: selected.placeId,
                                ),
                              ),
                            );
                          },
                          icon: const Icon(Icons.arrow_forward),
                          label: const Text('查看地点详情'),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              const SizedBox(height: JiYiSpacing.xl),
              const JiYiSectionHeader(
                title: '到访顺序',
                subtitle: '按服务端已经形成的 Visit 时间排序。',
              ),
              const SizedBox(height: JiYiSpacing.sm),
              if (visits.isEmpty)
                const JiYiSectionCard(
                  child: JiYiEmptyState(
                    icon: Icons.location_off_outlined,
                    title: '今天还没有形成足迹',
                    message: '这里不会用当前位置猜测你去过哪里。',
                  ),
                )
              else
                for (var index = 0; index < visits.length; index++) ...[
                  _VisitCard(
                    visit: visits[index],
                    order: index + 1,
                    selected: selected?.id == visits[index].id,
                    onTap: () {
                      final mapIndex =
                          mappable.indexWhere((item) => item.id == visits[index].id);
                      if (mapIndex >= 0) {
                        setState(() => _selectedIndex = mapIndex);
                      } else {
                        Navigator.of(context).push<void>(
                          MaterialPageRoute<void>(
                            builder: (_) => PlaceDetailPage(
                              api: widget.api,
                              placeId: visits[index].placeId,
                            ),
                          ),
                        );
                      }
                    },
                  ),
                  if (index != visits.length - 1)
                    const SizedBox(height: JiYiSpacing.sm),
                ],
            ],
          ),
        ),
      ),
    );
  }
}

class _VisitCard extends StatelessWidget {
  const _VisitCard({
    required this.visit,
    required this.order,
    required this.selected,
    required this.onTap,
  });

  final FootprintVisit visit;
  final int order;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: selected
          ? theme.colorScheme.primaryContainer
          : theme.colorScheme.surface,
      borderRadius: BorderRadius.circular(JiYiRadius.card),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        child: Padding(
          padding: const EdgeInsets.all(JiYiSpacing.md),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              CircleAvatar(
                radius: 17,
                child: Text(order.toString()),
              ),
              const SizedBox(width: JiYiSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      visit.placeName,
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: JiYiSpacing.xxs),
                    Text(_visitTime(visit)),
                    if (_visitDuration(visit) != null) ...[
                      const SizedBox(height: JiYiSpacing.xxs),
                      Text(
                        '停留 ${_visitDuration(visit)!}',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                    if (visit.address != null) ...[
                      const SizedBox(height: JiYiSpacing.xxs),
                      Text(
                        visit.address!,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const Icon(Icons.chevron_right),
            ],
          ),
        ),
      ),
    );
  }
}

String? _visitDuration(FootprintVisit visit) {
  final leftAt = visit.leftAt;
  if (leftAt == null) return null;
  final start = DateTime.tryParse(visit.arrivedAt);
  final end = DateTime.tryParse(leftAt);
  if (start == null || end == null || end.isBefore(start)) return null;
  final duration = end.difference(start);
  final hours = duration.inHours;
  final minutes = duration.inMinutes.remainder(60);
  if (hours > 0 && minutes > 0) return '$hours小时$minutes分钟';
  if (hours > 0) return '$hours小时';
  return '${duration.inMinutes}分钟';
}

String _visitTime(FootprintVisit visit) {
  final arrival = _clock(visit.arrivedAtLocal);
  final departure =
      visit.leftAtLocal == null ? null : _clock(visit.leftAtLocal!);
  return departure == null ? '$arrival 起' : '$arrival - $departure';
}

String _clock(String serverLocalIso) {
  final match = RegExp(r'T(\d{2}):(\d{2})').firstMatch(serverLocalIso);
  if (match == null) return '—';
  return '${match.group(1)!}:${match.group(2)!}';
}
