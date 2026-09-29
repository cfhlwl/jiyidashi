// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../ai_inference_presentation.dart';
import '../api_client.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';
import 'life_editors.dart';
import 'life_models.dart';
import 'memoir_models.dart';
import 'v2_api.dart';
import 'v2_authority.dart';
import 'v2_widgets.dart';

class MemoirsPage extends StatefulWidget {
  const MemoirsPage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<MemoirsPage> createState() => _MemoirsPageState();
}

class _MemoirsPageState extends State<MemoirsPage> {
  late final V2Api v2 = V2Api(widget.api);

  final V2Authority annualAuthority = V2Authority();
  final V2Authority annualTimelineAuthority = V2Authority();
  final V2Authority annualPhotoAuthority = V2Authority();
  final V2Authority mediaPreviewAuthority = V2Authority();
  final V2Authority memoirIndexAuthority = V2Authority();
  final V2Authority chapterAuthority = V2Authority();
  final V2OperationFlight annualFlight = V2OperationFlight();
  final V2OperationFlight chapterFlight = V2OperationFlight();

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

  @override
  void initState() {
    super.initState();
    year = TextEditingController(
      text: (DateTime.now().year - 1).toString().padLeft(4, '0'),
    );
    year.addListener(_yearChanged);
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
    final current = annual;
    final cursor = annualTimelineCursor;
    if (current == null || cursor == null) return;
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
        annualTimeline = List.unmodifiable([...annualTimeline, ...page.items]);
        annualTimelineCursor = page.nextCursor;
      });
    } catch (exc) {
      if (!mounted ||
          !annualTimelineAuthority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      setState(() => annualError = exc.toString());
    }
  }

  Future<void> _moreAnnualPhotos() async {
    final current = annual;
    final cursor = annualPhotoCursor;
    if (current == null || cursor == null) return;
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
        annualPhotos = List.unmodifiable([...annualPhotos, ...page.items]);
        annualPhotoCursor = page.nextCursor;
      });
    } catch (exc) {
      if (!mounted ||
          !annualPhotoAuthority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      setState(() => annualError = exc.toString());
    }
  }

  Future<void> _previewPhoto(V2AnnualMemoirPhoto photo) async {
    final current = annual;
    if (current == null) return;
    final identity = 'media:' + current.targetYear + ':' + photo.mediaId;
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = mediaPreviewAuthority.capture(widget.api, identity);
    } catch (exc) {
      if (mounted) setState(() => annualError = exc.toString());
      return;
    }
    try {
      final signed = await v2.getVerifiedMediaDownload(photo.mediaId);
      if (!mounted ||
          !mediaPreviewAuthority.isCurrent(widget.api, snapshot, identity) ||
          annual?.targetYear != current.targetYear) {
        return;
      }
      await showDialog<void>(
        context: context,
        builder: (_) => Dialog(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720, maxHeight: 720),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Flexible(
                  child: InteractiveViewer(
                    child: Image.network(
                      signed.url.toString(),
                      headers: signed.headers,
                      fit: BoxFit.contain,
                      errorBuilder: (_, __, ___) => const Padding(
                        padding: EdgeInsets.all(JiYiSpacing.lg),
                        child: Text('图片临时地址已失效，请关闭后重新打开。'),
                      ),
                    ),
                  ),
                ),
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('关闭'),
                ),
              ],
            ),
          ),
        ),
      );
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
        stages = append
            ? List.unmodifiable([...stages, ...page.items])
            : page.items;
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
    return Scaffold(
      appBar: AppBar(title: const Text('回忆总结')),
      body: SafeArea(
        child: JiYiPageFrame(
          title: '回忆总结',
          subtitle: '生成叙事使用 SEC-013；时间线、阶段索引和已验证照片保持各自确定性来源。',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _annualCard(),
              const SizedBox(height: JiYiSpacing.lg),
              _lifeMemoirCard(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _annualCard() {
    final result = annual;
    return V2SectionCard(
      title: '年度回顾',
      subtitle: '只有年度叙事是 AI 生成面；timeline/photo 不继承 AI 标签。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            controller: year,
            keyboardType: TextInputType.number,
            maxLength: 4,
            decoration: const InputDecoration(labelText: '年度'),
          ),
          FilledButton.icon(
            onPressed: annualLoading ? null : _generateAnnual,
            icon: const Icon(Icons.auto_awesome),
            label: Text(annualLoading ? '正在整理年度回顾…' : '生成年度回顾'),
          ),
          if (annualError != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            JiYiStatusBanner(kind: JiYiStatusKind.error, message: annualError!),
          ],
          if (result != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            V2KeyValue(label: '年度', value: result.targetYear),
            V2KeyValue(label: '时区', value: result.timezone),
            const SizedBox(height: JiYiSpacing.sm),
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
                subtitle: const Text('年度回顾基于你的相关记录整理。'),
              ),
            const Divider(),
            Text('年度时间线', style: Theme.of(context).textTheme.titleMedium),
            if (annualTimeline.isEmpty) const Text('当前没有时间线条目。'),
            for (final item in annualTimeline)
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(item.title),
                subtitle: Text(item.occurredAt),
              ),
            if (annualTimelineCursor != null)
              OutlinedButton(
                onPressed: _moreAnnualTimeline,
                child: const Text('继续加载时间线'),
              ),
            const Divider(),
            Text('已验证照片', style: Theme.of(context).textTheme.titleMedium),
            if (annualPhotos.isEmpty) const Text('当前没有可展示的已验证照片。'),
            for (final photo in annualPhotos)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.photo_outlined),
                title: Text(photo.title ?? '照片记忆'),
                subtitle: Text(photo.occurredAt),
                trailing: TextButton(
                  onPressed: () => _previewPhoto(photo),
                  child: const Text('查看'),
                ),
              ),
            if (annualPhotoCursor != null)
              OutlinedButton(
                onPressed: _moreAnnualPhotos,
                child: const Text('加载更多照片'),
              ),
          ],
        ],
      ),
    );
  }

  Widget _lifeMemoirCard() {
    final result = chapter;
    return V2SectionCard(
      title: '人生故事',
      subtitle: '选择一个人生阶段，需要时再让 AI 帮你整理成故事。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
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
                      (lifeStageLabels[item.stageKind] ?? item.stageKind) +
                          ' · ' +
                          item.startedAt +
                          ' → ' +
                          (item.endedAt ?? '开放'),
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
