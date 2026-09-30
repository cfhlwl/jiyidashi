// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';
import 'graph_models.dart';
import 'v2_api.dart';
import 'v2_authority.dart';
import 'v2_widgets.dart';

String _graphNodeLabel(String kind) {
  return switch (kind) {
    'PERSON' => '重要的人',
    'PLACE' => '地点',
    'OBJECT' => '物品',
    'EVENT' => '人生经历',
    _ => '相关内容',
  };
}

String _graphEdgeLabel(String kind) {
  return switch (kind) {
    'PERSON_RELATIONSHIP' => '你们的关系',
    'PERSON_EVENT' => '人物与经历',
    'OBJECT_PLACE' => '物品与地点',
    'EVENT_PLACE' => '经历与地点',
    _ => '相关',
  };
}

class GraphNeighborhoodPage extends StatefulWidget {
  const GraphNeighborhoodPage({
    super.key,
    required this.api,
    required this.kind,
    required this.entityId,
    required this.title,
  });

  final JiYiApiClient api;
  final String kind;
  final String entityId;
  final String title;

  @override
  State<GraphNeighborhoodPage> createState() => _GraphNeighborhoodPageState();
}

class _GraphNeighborhoodPageState extends State<GraphNeighborhoodPage> {
  late final V2Api v2 = V2Api(widget.api);
  final V2Authority authority = V2Authority();
  V2GraphNeighborhood? graph;
  bool loading = true;
  String? error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(GraphNeighborhoodPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.kind != widget.kind || oldWidget.entityId != widget.entityId) {
      authority.invalidate();
      graph = null;
      _load();
    }
  }

  @override
  void dispose() {
    authority.invalidate();
    super.dispose();
  }

  Future<void> _load() async {
    final identity = 'graph:' + widget.kind + ':' + widget.entityId;
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = authority.capture(widget.api, identity);
    } catch (exc) {
      if (mounted) setState(() { loading = false; error = exc.toString(); });
      return;
    }
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final result = await v2.graphNeighborhood(
        kind: widget.kind,
        entityId: widget.entityId,
        limit: 50,
      );
      if (!mounted || !authority.isCurrent(widget.api, snapshot, identity)) {
        return;
      }
      setState(() {
        graph = result;
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
      appBar: AppBar(title: Text(widget.title + ' · 相关的人和事')),
      body: SafeArea(
        child: JiYiPageFrame(
          title: '相关的人和事',
          subtitle: '查看与当前内容直接相关的人、地点、物品和经历。',
          child: loading
              ? const Center(child: CircularProgressIndicator())
              : error != null
                  ? V2ErrorState(message: error!, onRetry: _load)
                  : _GraphView(graph: graph!),
        ),
      ),
    );
  }
}

class _GraphView extends StatelessWidget {
  const _GraphView({required this.graph});

  final V2GraphNeighborhood graph;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        V2SectionCard(
          title: '当前内容',
          child: ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.hub_outlined),
            title: Text(graph.center.label),
            subtitle: Text(_graphNodeLabel(graph.center.kind)),
          ),
        ),
        const SizedBox(height: JiYiSpacing.md),
        V2SectionCard(
          title: '相关内容',
          subtitle: graph.truncated ? '这里只显示部分直接相关内容' : '显示当前直接相关内容',
          child: Wrap(
            spacing: JiYiSpacing.sm,
            runSpacing: JiYiSpacing.sm,
            children: [
              for (final node in graph.nodes)
                Semantics(
                  label: '相关内容：' + node.label + '，' + _graphNodeLabel(node.kind),
                  child: Chip(
                    avatar: const Icon(Icons.circle_outlined, size: 18),
                    label: Text(node.label + ' · ' + _graphNodeLabel(node.kind)),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: JiYiSpacing.md),
        V2SectionCard(
          title: '关联方式',
          child: Column(
            children: [
              if (graph.edges.isEmpty)
                const Text('当前没有可展示的相关内容。'),
              for (final edge in graph.edges)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.link),
                  title: Text(edge.source.label + ' → ' + edge.target.label),
                  subtitle: Text(_graphEdgeLabel(edge.kind)),
                ),
            ],
          ),
        ),
      ],
    );
  }
}
