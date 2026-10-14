// ignore_for_file: prefer_interpolation_to_compose_strings

import 'dart:io';

import 'package:flutter/material.dart';

import '../ai_inference_presentation.dart';
import '../api_client.dart';
import '../media_presentation_cache.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_format.dart';
import '../ui/jiyi_timezone.dart';
import '../ui/jiyi_tokens.dart';
import '../ui/jiyi_v3_components.dart';
import 'life_editors.dart';
import 'life_models.dart';
import 'memoir_models.dart';
import 'v2_api.dart';
import 'v2_authority.dart';
import 'v2_widgets.dart';

typedef MemoirPhotoRenderer = Widget Function(File file);

class MemoirsPage extends StatefulWidget {
  const MemoirsPage({
    super.key,
    required this.api,
    this.mediaCache,
    this.photoRenderer,
  });

  final JiYiApiClient api;
  final LocalMediaCache? mediaCache;
  final MemoirPhotoRenderer? photoRenderer;

  @override
  State<MemoirsPage> createState() => _MemoirsPageState();
}

class _MemoirsPageState extends State<MemoirsPage> {
  late final V2Api v2 = V2Api(widget.api);
  late final LocalMediaCache _mediaCache =
      widget.mediaCache ?? LocalMediaCache();

  final V2Authority annualAuthority = V2Authority();
  final V2Authority annualTimelineAuthority = V2Authority();
  final V2Authority annualPhotoAuthority = V2Authority();
  final V2Authority mediaPreviewAuthority = V2Authority();
  final V2Authority memoirIndexAuthority = V2Authority();
  final V2Authority chapterAuthority = V2Authority();
  final V2OperationFlight annualFlight = V2OperationFlight();
  final V2OperationFlight chapterFlight = V2OperationFlight();

  JiYiApiClient? _boundApi;
  String? _boundOwner;
  int? _boundSessionVersion;
  bool _rebindScheduled = false;
  bool annualTimelineLoading = false;
  bool annualPhotoLoading = false;
  Route<dynamic>? _previewRoute;
  bool _previewOpen = false;

  late final TextEditingController year;

  V2AnnualMemoir? annual;
  List<V2LifeHistoryItem> annualTimeline = const [];
  String? annualTimelineCursor;
  List<V2AnnualMemoirPhoto> annualPhotos = const [];
  String? annualPhotoCursor;
  bool annualLoading = false;
  String? annualError;

  List<V2LifeMemoirStage> stages = const [];
  String? stageCursor;
  bool stageLoading = false;
  String? stageError;
  String? selectedStageId;
  V2LifeMemoirChapter? chapter;
  bool chapterLoading = false;
  String? chapterError;

  bool get _bindingMatches =>
      identical(_boundApi, widget.api) &&
      _boundOwner == widget.api.authenticatedUserId &&
      _boundSessionVersion == widget.api.sessionVersion;

  @override
  void initState() {
    super.initState();
    _rememberBinding();
    year = TextEditingController(
      text: (DateTime.now().year - 1).toString().padLeft(4, '0'),
    );
    year.addListener(_yearChanged);
    _loadStages(append: false);
  }

  void _rememberBinding() {
    _boundApi = widget.api;
    _boundOwner = widget.api.authenticatedUserId;
    _boundSessionVersion = widget.api.sessionVersion;
  }

  @override
  void didUpdateWidget(covariant MemoirsPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.api, widget.api)) _scheduleRebind();
  }

  void _scheduleRebind() {
    if (_rebindScheduled) return;
    _rebindScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _rebindScheduled = false;
      if (mounted) _rebind();
    });
  }

  void _checkBinding() {
    if (!_bindingMatches) _scheduleRebind();
  }

  void _rebind() {
    annualAuthority.invalidate();
    annualTimelineAuthority.invalidate();
    annualPhotoAuthority.invalidate();
    mediaPreviewAuthority.invalidate();
    memoirIndexAuthority.invalidate();
    chapterAuthority.invalidate();
    annualFlight.invalidate();
    chapterFlight.invalidate();
    final route = _previewRoute;
    if (_previewOpen && route != null && route.isActive) {
      route.navigator?.removeRoute(route);
    }
    _previewRoute = null;
    _previewOpen = false;
    _rememberBinding();
    if (!mounted) return;
    setState(() {
      annual = null;
      annualTimeline = const [];
      annualTimelineCursor = null;
      annualPhotos = const [];
      annualPhotoCursor = null;
      annualLoading = false;
      annualTimelineLoading = false;
      annualPhotoLoading = false;
      annualError = null;
      stages = const [];
      stageCursor = null;
      stageLoading = false;
      stageError = null;
      selectedStageId = null;
      chapter = null;
      chapterLoading = false;
      chapterError = null;
    });
    _loadStages(append: false);
  }

  @override
  void dispose() {
    year.removeListener(_yearChanged);
    year.dispose();
    annualAuthority.invalidate();
    annualTimelineAuthority.invalidate();
    annualPhotoAuthority.invalidate();
    mediaPreviewAuthority.invalidate();
    memoirIndexAuthority.invalidate();
    chapterAuthority.invalidate();
    annualFlight.invalidate();
    chapterFlight.invalidate();
    super.dispose();
  }

  void _yearChanged() {
    annualAuthority.invalidate();
    annualTimelineAuthority.invalidate();
    annualPhotoAuthority.invalidate();
    mediaPreviewAuthority.invalidate();
    annualFlight.invalidate();
    if (!mounted) return;
    setState(() {
      annual = null;
      annualTimeline = const [];
      annualTimelineCursor = null;
      annualPhotos = const [];
      annualPhotoCursor = null;
      annualLoading = false;
      annualError = null;
      annualTimelineLoading = false;
      annualPhotoLoading = false;
    });
  }

  String? _validYear() {
    final value = year.text.trim();
    if (!RegExp(r'^[0-9]{4}$').hasMatch(value)) return null;
    final numeric = int.tryParse(value);
    if (numeric == null || numeric < 1 || numeric > 9998) return null;
    return value;
  }

  bool _operationCurrent(
    V2Authority authority,
    V2OperationFlight flight,
    V2OperationContext operation,
  ) =>
      mounted &&
      authority.isCurrent(
        widget.api,
        operation.snapshot,
        operation.snapshot.identity,
      ) &&
      flight.isCurrent(operation.token, widget.api);

  String _timelineItemKey(V2LifeHistoryItem item) =>
      '${item.kind}:${item.lifeEventId ?? item.lifeStageId ?? item.title}:${item.occurredAt}';

  Future<void> _generateAnnual() async {
    final target = _validYear();
    if (target == null) {
      setState(() => annualError = '年度必须是 0001–9998 的四位年份');
      return;
    }
    final operation = beginV2Operation(
      widget.api,
      annualAuthority,
      annualFlight,
      'annual:' + target,
    );
    if (operation == null) return;
    annualTimelineAuthority.invalidate();
    annualPhotoAuthority.invalidate();
    mediaPreviewAuthority.invalidate();
    setState(() {
      annualLoading = true;
      annualError = null;
      annual = null;
      annualTimeline = const [];
      annualTimelineCursor = null;
      annualPhotos = const [];
      annualPhotoCursor = null;
      annualTimelineLoading = false;
      annualPhotoLoading = false;
    });
    try {
      final result = await v2.generateAnnualMemoir(target);
      if (!_operationCurrent(annualAuthority, annualFlight, operation)) return;
      setState(() {
        annual = result;
        annualTimeline = result.timelineItems;
        annualTimelineCursor = result.timelineNextCursor;
        annualPhotos = result.photoItems;
        annualPhotoCursor = result.photoNextCursor;
        annualLoading = false;
      });
    } catch (exc) {
      if (!_operationCurrent(annualAuthority, annualFlight, operation)) return;
      setState(() {
        annualError = exc.toString();
        annualLoading = false;
      });
    } finally {
      annualFlight.end(operation.token);
    }
  }

  Future<void> _moreAnnualTimeline() async {
    if (annualTimelineLoading) return;
    final current = annual;
    final cursor = annualTimelineCursor;
    if (current == null || cursor == null) return;
    annualTimelineLoading = true;
    final identity = 'annual-timeline:' + current.targetYear + ':' + cursor;
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = annualTimelineAuthority.capture(widget.api, identity);
    } catch (exc) {
      if (mounted) setState(() => annualError = exc.toString());
      return;
    }
    try {
      final page = await v2.getLifeHistory(
        startYear: int.parse(current.targetYear),
        endYear: int.parse(current.targetYear),
        limit: 50,
        cursor: cursor,
      );
      if (!mounted ||
          !annualTimelineAuthority.isCurrent(widget.api, snapshot, identity) ||
          annual?.targetYear != current.targetYear) {
        return;
      }
      setState(() {
        final merged = <String, V2LifeHistoryItem>{
          for (final item in annualTimeline) _timelineItemKey(item): item,
          for (final item in page.items) _timelineItemKey(item): item,
        };
        annualTimeline = List.unmodifiable(merged.values);
        annualTimelineCursor = page.nextCursor;
        annualTimelineLoading = false;
      });
    } catch (exc) {
      if (!mounted ||
          !annualTimelineAuthority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      setState(() {
        annualError = exc.toString();
        annualTimelineLoading = false;
      });
    }
  }

  Future<void> _moreAnnualPhotos() async {
    if (annualPhotoLoading) return;
    final current = annual;
    final cursor = annualPhotoCursor;
    if (current == null || cursor == null) return;
    annualPhotoLoading = true;
    final identity = 'annual-photos:' + current.targetYear + ':' + cursor;
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = annualPhotoAuthority.capture(widget.api, identity);
    } catch (exc) {
      if (mounted) setState(() => annualError = exc.toString());
      return;
    }
    try {
      final page = await v2.getAnnualMemoirPhotos(
        current.targetYear,
        limit: 24,
        cursor: cursor,
      );
      if (!mounted ||
          !annualPhotoAuthority.isCurrent(widget.api, snapshot, identity) ||
          annual?.targetYear != current.targetYear) {
        return;
      }
      setState(() {
        final merged = <String, V2AnnualMemoirPhoto>{
          for (final item in annualPhotos) item.mediaId: item,
          for (final item in page.items) item.mediaId: item,
        };
        annualPhotos = List.unmodifiable(merged.values);
        annualPhotoCursor = page.nextCursor;
        annualPhotoLoading = false;
      });
    } catch (exc) {
      if (!mounted ||
          !annualPhotoAuthority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      setState(() {
        annualError = exc.toString();
        annualPhotoLoading = false;
      });
    }
  }

  Future<void> _previewPhoto(V2AnnualMemoirPhoto photo) async {
    final current = annual;
    final owner = widget.api.authenticatedUserId;
    if (current == null || owner == null || owner.trim().isEmpty) return;
    final identity = 'media:' + current.targetYear + ':' + photo.mediaId;
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = mediaPreviewAuthority.capture(widget.api, identity);
    } catch (exc) {
      if (mounted) setState(() => annualError = exc.toString());
      return;
    }
    try {
      final localFile = await MediaPresentationResolver(
        api: widget.api,
        cache: _mediaCache,
      ).resolve(
        ownerUserId: owner,
        mediaId: photo.mediaId,
      );
      if (!mounted ||
          !mediaPreviewAuthority.isCurrent(widget.api, snapshot, identity) ||
          annual?.targetYear != current.targetYear) {
        return;
      }
      final navigator = Navigator.of(context, rootNavigator: true);
      final route = DialogRoute<void>(
        context: context,
        builder: (_) => Dialog(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720, maxHeight: 720),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Flexible(
                  child: InteractiveViewer(
                    child: widget.photoRenderer?.call(localFile) ??
                        LocalMediaPresentationScope.maybeOf(context)?.renderer(
                          context,
                          localFile,
                          BoxFit.contain,
                        ) ??
                        _defaultMemoirPhotoRenderer(localFile),
                  ),
                ),
                TextButton(
                  onPressed: () => Navigator.of(context).pop(),
                  child: const Text('关闭'),
                ),
              ],
            ),
          ),
        ),
      );
      _previewRoute = route;
      _previewOpen = true;
      try {
        await navigator.push<void>(route);
      } finally {
        _previewOpen = false;
        if (identical(_previewRoute, route)) _previewRoute = null;
      }
    } on MediaUnavailableOffline {
      if (!mounted ||
          !mediaPreviewAuthority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      setState(() => annualError = '这张照片尚未缓存，离线时暂时无法显示。');
    } catch (exc) {
      if (!mounted ||
          !mediaPreviewAuthority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      setState(() => annualError = exc.toString());
    }
  }

  Future<void> _loadStages({required bool append}) async {
    final next = append ? stageCursor : null;
    if (append && next == null) return;
    final identity = 'memoir-stages:' + (next ?? 'root');
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = memoirIndexAuthority.capture(widget.api, identity);
    } catch (exc) {
      if (mounted) setState(() => stageError = exc.toString());
      return;
    }
    setState(() {
      stageLoading = true;
      stageError = null;
      if (!append) {
        stages = const [];
        stageCursor = null;
      }
    });
    try {
      final page = await v2.getLifeMemoirStages(limit: 50, cursor: next);
      if (!mounted ||
          !memoirIndexAuthority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      setState(() {
        final merged = <String, V2LifeMemoirStage>{
          if (append) for (final item in stages) item.lifeStageId: item,
          for (final item in page.items) item.lifeStageId: item,
        };
        stages = List.unmodifiable(merged.values);
        stageCursor = page.nextCursor;
        stageLoading = false;
      });
    } catch (exc) {
      if (!mounted ||
          !memoirIndexAuthority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      setState(() {
        stageError = exc.toString();
        stageLoading = false;
      });
    }
  }

  void _selectStage(String stageId) {
    chapterAuthority.invalidate();
    chapterFlight.invalidate();
    setState(() {
      selectedStageId = stageId;
      chapter = null;
      chapterError = null;
      chapterLoading = false;
    });
  }

  Future<void> _generateChapter() async {
    final stageId = selectedStageId;
    if (stageId == null) return;
    final operation = beginV2Operation(
      widget.api,
      chapterAuthority,
      chapterFlight,
      'chapter:' + stageId,
    );
    if (operation == null) return;
    setState(() {
      chapter = null;
      chapterError = null;
      chapterLoading = true;
    });
    try {
      final result = await v2.generateLifeMemoirChapter(stageId);
      if (!_operationCurrent(chapterAuthority, chapterFlight, operation) ||
          selectedStageId != stageId) {
        return;
      }
      setState(() {
        chapter = result;
        chapterLoading = false;
      });
    } catch (exc) {
      if (!_operationCurrent(chapterAuthority, chapterFlight, operation)) {
        return;
      }
      setState(() {
        chapterError = exc.toString();
        chapterLoading = false;
      });
    } finally {
      chapterFlight.end(operation.token);
    }
  }

  @override
  Widget build(BuildContext context) {
    _checkBinding();
    return V3PageScaffold(
      topBar: V3TopBar(
        title: '回忆总结',
        subtitle: '从真实照片、时间和经历中慢慢回看',
        onBack: () => Navigator.of(context).maybePop(),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          V3SurfaceCard(
            color: Theme.of(context).colorScheme.primaryContainer,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('把生活翻回来', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
                const SizedBox(height: JiYiSpacing.xs),
                Text('先看已经保存的记录，再决定是否生成一段有依据的故事。'),
              ],
            ),
          ),
          const SizedBox(height: JiYiSpacing.xl),
          _annualCard(),
          const SizedBox(height: JiYiSpacing.xxl),
          _lifeMemoirCard(),
        ],
      ),
    );
  }

  Widget _annualCard() {
    final result = annual;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const JiYiSectionHeader(
          title: '年度回顾',
          subtitle: '选择一年，用已经保存的照片和记录回看那一年的生活。',
        ),
        const SizedBox(height: JiYiSpacing.md),
        V3SurfaceCard(
          child: LayoutBuilder(
            builder: (context, constraints) {
              final field = TextField(
                controller: year,
                keyboardType: TextInputType.number,
                maxLength: 4,
                decoration: const InputDecoration(
                  labelText: '想回看的年份',
                  hintText: '例如 2025',
                ),
              );
              final action = FilledButton.icon(
                onPressed: annualLoading ? null : _generateAnnual,
                icon: const Icon(Icons.auto_awesome),
                label: Text(annualLoading ? '整理中…' : '开始回看'),
              );
              return constraints.maxWidth < 360
                  ? Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [field, action],
                    )
                  : Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(child: field),
                        const SizedBox(width: JiYiSpacing.sm),
                        action,
                      ],
                    );
            },
          ),
        ),
        if (annualError != null) ...[
          const SizedBox(height: JiYiSpacing.sm),
          JiYiStatusBanner(kind: JiYiStatusKind.error, message: annualError!),
        ],
        if (result != null) ...[
          const SizedBox(height: JiYiSpacing.lg),
          _AnnualStoryHero(
            key: const ValueKey('annual-story-hero'),
            year: result.targetYear,
            presentation: result.presentation,
            narrativeStatus: result.narrativeStatus,
            narrative: result.narrative,
          ),
          const SizedBox(height: JiYiSpacing.xl),
          JiYiSectionHeader(
            title: '这一年的照片',
            subtitle: annualPhotos.isEmpty
                ? '这一年还没有可展示的照片。'
                : '照片先于文字，点开可以查看原图。',
          ),
          const SizedBox(height: JiYiSpacing.sm),
          if (annualPhotos.isEmpty)
            const JiYiEmptyState(
              icon: Icons.photo_outlined,
              title: '还没有照片片段',
              message: '以后保存的照片会在年度回顾里成为可回看的生活片段。',
            )
          else
            SizedBox(
              height: 164,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: annualPhotos.length,
                separatorBuilder: (_, __) => const SizedBox(width: JiYiSpacing.sm),
                itemBuilder: (context, index) {
                  final photo = annualPhotos[index];
                  return _AnnualPhotoCard(
                    api: widget.api,
                    mediaCache: _mediaCache,
                    photo: photo,
                    timezone: result.timezone,
                    onTap: () => _previewPhoto(photo),
                  );
                },
              ),
            ),
          if (annualPhotoCursor != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton.icon(
                onPressed: annualPhotoLoading ? null : _moreAnnualPhotos,
                icon: const Icon(Icons.add_photo_alternate_outlined),
                label: Text(annualPhotoLoading ? '正在读取…' : '查看更多照片'),
              ),
            ),
          ],
          const SizedBox(height: JiYiSpacing.xl),
          JiYiSectionHeader(
            title: '这一年的时间线',
            subtitle: annualTimeline.isEmpty
                ? '这一年还没有可展示的重要片段。'
                : '按时间回看已经形成的人生经历和阶段。',
          ),
          const SizedBox(height: JiYiSpacing.sm),
          if (annualTimeline.isEmpty)
            const JiYiEmptyState(
              icon: Icons.timeline_outlined,
              title: '还没有时间线片段',
              message: '已经记录的重要经历会慢慢出现在这里。',
            )
          else
            for (var index = 0; index < annualTimeline.length; index++)
              _AnnualTimelineRow(
                item: annualTimeline[index],
                timezone: result.timezone,
                isLast: index == annualTimeline.length - 1,
              ),
          if (annualTimelineCursor != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton.icon(
                onPressed: annualTimelineLoading ? null : _moreAnnualTimeline,
                icon: const Icon(Icons.expand_more),
                label: Text(annualTimelineLoading ? '正在读取…' : '继续回看'),
              ),
            ),
          ],
          if (result.citations.isNotEmpty) ...[
            const SizedBox(height: JiYiSpacing.xl),
            const JiYiSectionHeader(
              title: '参考记录',
              subtitle: '这段年度故事只基于你已有的相关记录整理。',
            ),
            const SizedBox(height: JiYiSpacing.sm),
            Wrap(
              spacing: JiYiSpacing.xs,
              runSpacing: JiYiSpacing.xs,
              children: [
                for (var index = 0; index < result.citations.length; index++)
                  Chip(
                    avatar: const Icon(Icons.fact_check_outlined, size: 18),
                    label: Text('参考记录 ${index + 1}'),
                  ),
              ],
            ),
          ],
        ],
      ],
    );
  }

  Widget _lifeMemoirCard() {
    final result = chapter;
    return V3SurfaceCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const V3SectionHeader(
            title: '人生故事',
            subtitle: '选择一个真实人生阶段，需要时再生成有依据的章节。',
          ),
          const SizedBox(height: JiYiSpacing.md),
          OutlinedButton(
            onPressed: stageLoading ? null : () => _loadStages(append: false),
            child: Text(stageLoading ? '加载中…' : '刷新人生阶段'),
          ),
          if (stageError != null)
            JiYiStatusBanner(kind: JiYiStatusKind.error, message: stageError!),
          RadioGroup<String>(
            groupValue: selectedStageId,
            onChanged: (value) {
              if (value != null) _selectStage(value);
            },
            child: Column(
              children: [
                for (final item in stages)
                  RadioListTile<String>(
                    value: item.lifeStageId,
                    title: Text(item.title),
                    subtitle: Text(
                      (lifeStageLabels[item.stageKind] ?? '其他阶段') +
                          ' · ' +
                          jiyiDisplayDate(item.startedAt) +
                          ' → ' +
                          (item.endedAt == null
                              ? '至今'
                              : jiyiDisplayDate(item.endedAt!)),
                    ),
                  ),
              ],
            ),
          ),
          if (stageCursor != null)
            OutlinedButton(
              onPressed: stageLoading ? null : () => _loadStages(append: true),
              child: const Text('加载更多阶段'),
            ),
          if (selectedStageId != null)
            FilledButton.icon(
              onPressed: chapterLoading ? null : _generateChapter,
              icon: const Icon(Icons.auto_awesome),
              label: Text(chapterLoading ? '正在整理故事…' : '生成这个阶段的故事'),
            ),
          if (chapterError != null)
            JiYiStatusBanner(kind: JiYiStatusKind.error, message: chapterError!),
          if (result != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            V2TrustBadge(presentation: result.presentation),
            const SizedBox(height: JiYiSpacing.xs),
            Text(result.presentation.detail),
            if (result.presentation.state == AiPresentationState.inferred &&
                result.narrative != null) ...[
              const SizedBox(height: JiYiSpacing.sm),
              Text(result.narrative!),
            ],
            for (var index = 0; index < result.citations.length; index++)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.fact_check_outlined),
                title: Text('参考记录 ${index + 1}'),
                subtitle: const Text('这段故事基于你已有的相关记录整理。'),
              ),
          ],
        ],
      ),
    );
  }
}


class _AnnualStoryHero extends StatelessWidget {
  const _AnnualStoryHero({
    super.key,
    required this.year,
    required this.presentation,
    required this.narrativeStatus,
    required this.narrative,
  });

  final String year;
  final AiPresentation presentation;
  final String narrativeStatus;
  final String? narrative;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(JiYiRadius.large),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: theme.brightness == Brightness.dark
              ? const [
                  Color(0xFF203A59),
                  Color(0xFF172B45),
                ]
              : const [
                  Color(0xFFFFF3E4),
                  Color(0xFFEAF3FA),
                ],
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(JiYiSpacing.xl),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              year,
              style: theme.textTheme.displaySmall?.copyWith(
                fontWeight: FontWeight.w800,
                color: theme.colorScheme.onSurface,
              ),
            ),
            const SizedBox(height: JiYiSpacing.xs),
            Text(
              narrativeStatus == 'NO_SUMMARIZABLE_EVIDENCE'
                  ? '还没有足够的记录'
                  : '这一年的故事',
              style: theme.textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: JiYiSpacing.md),
            V2TrustBadge(presentation: presentation),
            const SizedBox(height: JiYiSpacing.sm),
            Text(
              narrativeStatus == 'NO_SUMMARIZABLE_EVIDENCE'
                  ? '目前没有足够的真实记录来生成年度回顾。'
                  : presentation.detail,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
                height: 1.5,
              ),
            ),
            if (presentation.state == AiPresentationState.inferred &&
                narrative != null) ...[
              const SizedBox(height: JiYiSpacing.md),
              Text(
                narrative!,
                style: theme.textTheme.bodyLarge?.copyWith(
                  height: 1.7,
                  color: theme.colorScheme.onSurface,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _AnnualPhotoCard extends StatelessWidget {
  const _AnnualPhotoCard({
    required this.api,
    required this.mediaCache,
    required this.photo,
    required this.timezone,
    required this.onTap,
  });

  final JiYiApiClient api;
  final LocalMediaCache mediaCache;
  final V2AnnualMemoirPhoto photo;
  final String timezone;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SizedBox(
      width: 184,
      child: Material(
        color: theme.colorScheme.surface,
        borderRadius: BorderRadius.circular(JiYiRadius.card),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          borderRadius: BorderRadius.circular(JiYiRadius.card),
          onTap: onTap,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                child: LocalMediaThumbnail(
                  key: ValueKey('annual-photo-${photo.mediaId}'),
                  api: api,
                  mediaId: photo.mediaId,
                  cache: mediaCache,
                  width: 184,
                  height: 104,
                  borderRadius: 0,
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  JiYiSpacing.md,
                  JiYiSpacing.sm,
                  JiYiSpacing.md,
                  JiYiSpacing.md,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      photo.title ?? '照片记忆',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: JiYiSpacing.xxs),
                    Text(
                      _dateLabel(),
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
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

  String _dateLabel() {
    final wall = jiyiDateTimeInTimezone(photo.occurredAt, timezone);
    if (wall == null) return jiyiDisplayDate(photo.occurredAt);
    return '${wall.year}年${wall.month}月${wall.day}日';
  }
}

class _AnnualTimelineRow extends StatelessWidget {
  const _AnnualTimelineRow({
    required this.item,
    required this.timezone,
    required this.isLast,
  });

  final V2LifeHistoryItem item;
  final String timezone;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 76,
          child: Padding(
            padding: const EdgeInsets.only(top: JiYiSpacing.sm),
            child: Text(
              _dateLabel(),
              textAlign: TextAlign.end,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ),
        ),
        const SizedBox(width: JiYiSpacing.sm),
        SizedBox(
          width: 18,
          child: Column(
            children: [
              const SizedBox(height: JiYiSpacing.sm),
              Container(
                width: 10,
                height: 10,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: theme.colorScheme.primary,
                ),
              ),
              if (!isLast)
                Container(
                  width: 2,
                  height: 58,
                  color: theme.colorScheme.outlineVariant,
                ),
            ],
          ),
        ),
        const SizedBox(width: JiYiSpacing.sm),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.only(bottom: JiYiSpacing.md),
            child: Text(
              item.title,
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ),
      ],
    );
  }

  String _dateLabel() {
    final wall = jiyiDateTimeInTimezone(item.occurredAt, timezone);
    if (wall == null) return jiyiDisplayDate(item.occurredAt);
    return '${wall.month}月${wall.day}日';
  }
}


Widget _defaultMemoirPhotoRenderer(File file) {
  return Image.file(
    file,
    fit: BoxFit.contain,
    errorBuilder: (_, __, ___) => const Padding(
      padding: EdgeInsets.all(JiYiSpacing.lg),
      child: Text('本地照片缓存已损坏，请关闭后重新打开。'),
    ),
  );
}
