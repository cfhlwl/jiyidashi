import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';
import 'life_models.dart';
import 'v2_api.dart';
import 'v2_authority.dart';
import 'v2_widgets.dart';

class LifeHistoryPage extends StatefulWidget {
  const LifeHistoryPage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<LifeHistoryPage> createState() => _LifeHistoryPageState();
}

class _LifeHistoryPageState extends State<LifeHistoryPage> {
  late final V2Api v2 = V2Api(widget.api);
  final V2Authority authority = V2Authority();
  late final TextEditingController startYear;
  late final TextEditingController endYear;

  V2LifeHistoryPage? page;
  List<V2LifeHistoryItem> items = const [];
  String? cursor;
  bool loading = false;
  String? error;

  @override
  void initState() {
    super.initState();
    final year = DateTime.now().year;
    startYear = TextEditingController(text: (year - 5).toString());
    endYear = TextEditingController(text: year.toString());
    startYear.addListener(_rangeChanged);
    endYear.addListener(_rangeChanged);
  }

  @override
  void dispose() {
    startYear.removeListener(_rangeChanged);
    endYear.removeListener(_rangeChanged);
    startYear.dispose();
    endYear.dispose();
    authority.invalidate();
    super.dispose();
  }

  void _rangeChanged() {
    authority.invalidate();
    if (!mounted) return;
    setState(() {
      page = null;
      items = const [];
      cursor = null;
      error = null;
      loading = false;
    });
  }

  ({int start, int end})? _range() {
    final start = int.tryParse(startYear.text.trim());
    final end = int.tryParse(endYear.text.trim());
    if (start == null || end == null || start < 1 || end > 9998 || start > end) {
      return null;
    }
    return (start: start, end: end);
  }

  Future<void> _load({required bool append}) async {
    final range = _range();
    if (range == null) {
      setState(() => error = '年份范围无效');
      return;
    }
    final nextCursor = append ? cursor : null;
    if (append && nextCursor == null) return;
    final identity = 'history:' +
        range.start.toString() +
        ':' +
        range.end.toString() +
        ':' +
        (nextCursor ?? 'root');
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = authority.capture(widget.api, identity);
    } catch (exc) {
      if (mounted) setState(() => error = exc.toString());
      return;
    }
    setState(() {
      loading = true;
      error = null;
      if (!append) {
        page = null;
        items = const [];
        cursor = null;
      }
    });
    try {
      final result = await v2.getLifeHistory(
        startYear: range.start,
        endYear: range.end,
        limit: 50,
        cursor: nextCursor,
      );
      if (!mounted || !authority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      setState(() {
        page = result;
        items = append
            ? List.unmodifiable([...items, ...result.items])
            : result.items;
        cursor = result.nextCursor;
        loading = false;
      });
    } catch (exc) {
      if (!mounted || !authority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      setState(() {
        error = exc.toString();
        loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('跨年时间线')),
      body: SafeArea(
        child: JiYiPageFrame(
          title: '跨年时间线',
          subtitle: '确定性服务端投影；游标是 opaque token，客户端不解析、不重写。',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: startYear,
                      keyboardType: TextInputType.number,
                      decoration: const InputDecoration(labelText: '开始年份'),
                    ),
                  ),
                  const SizedBox(width: JiYiSpacing.sm),
                  Expanded(
                    child: TextField(
                      controller: endYear,
                      keyboardType: TextInputType.number,
                      decoration: const InputDecoration(labelText: '结束年份'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: JiYiSpacing.sm),
              FilledButton(
                onPressed: loading ? null : () => _load(append: false),
                child: Text(loading && items.isEmpty ? '加载中…' : '查看时间线'),
              ),
              if (error != null) ...[
                const SizedBox(height: JiYiSpacing.md),
                V2ErrorState(
                  message: error!,
                  onRetry: () => _load(append: false),
                ),
              ],
              if (page != null) ...[
                const SizedBox(height: JiYiSpacing.md),
                JiYiSectionCard(
                  title: '服务端范围',
                  child: Text(
                    page!.startYear.toString() +
                        '–' +
                        page!.endYear.toString() +
                        ' · ' +
                        page!.timezone +
                        ' · as_of ' +
                        page!.asOf,
                  ),
                ),
              ],
              if (items.isNotEmpty) ...[
                const SizedBox(height: JiYiSpacing.md),
                JiYiSectionCard(
                  title: '时间线',
                  child: Column(
                    children: [
                      for (final item in items)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: Icon(
                            item.kind == 'LIFE_EVENT'
                                ? Icons.event_note_outlined
                                : Icons.view_timeline_outlined,
                          ),
                          title: Text(item.title),
                          subtitle: Text(item.kind + ' · ' + item.occurredAt),
                        ),
                    ],
                  ),
                ),
              ],
              if (cursor != null) ...[
                const SizedBox(height: JiYiSpacing.sm),
                OutlinedButton(
                  onPressed: loading ? null : () => _load(append: true),
                  child: Text(loading ? '加载中…' : '加载更多'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
