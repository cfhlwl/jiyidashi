import 'package:flutter/material.dart';

import '../api_client.dart';
import '../ui/jiyi_tokens.dart';
import '../ui/jiyi_v3_components.dart';
import 'graph_models.dart';
import 'person_detail_page.dart';
import 'v2_api.dart';
import 'v2_authority.dart';

String _graphNodeLabel(String kind) => switch (kind) {
  'PERSON' => '重要的人',
  'PLACE' => '地点',
  'OBJECT' => '物品',
  'EVENT' => '人生经历',
  _ => '相关内容',
};

String _graphEdgeKindLabel(String kind) => switch (kind) {
  'PERSON_RELATIONSHIP' => '人物关系',
  'PERSON_EVENT' => '人物与经历',
  'OBJECT_PLACE' => '物品与地点',
  'EVENT_PLACE' => '经历与地点',
  _ => '相关内容',
};

String _relationshipLabel(String? value, String? customLabel) {
  return switch (value) {
    'FAMILY' => '家人',
    'FRIEND' => '朋友',
    'COLLEAGUE' => '同事',
    'CLASSMATE' => '同学',
    'OTHER' => customLabel?.trim().isNotEmpty == true ? customLabel! : '其他关系',
    _ => '已记录关系',
  };
}

String _personMemoryRelationLabel(String? value) => switch (value) {
  'MET' => '见过 / 互动过',
  'RELATED' => '相关记忆',
  _ => '人物与经历',
};

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
  late V2Api v2;
  final V2Authority authority = V2Authority();
  JiYiApiClient? _boundApi;
  String? _boundOwner;
  int? _boundSessionVersion;
  String? _boundKind;
  String? _boundEntityId;
  V2AuthoritySnapshot? _activeSnapshot;
  V2GraphNeighborhood? graph;
  bool loading = true;
  String? error;
  bool _rebindScheduled = false;

  @override
  void initState() {
    super.initState();
    v2 = V2Api(widget.api);
    _rememberBinding();
    _load();
  }

  @override
  void didUpdateWidget(GraphNeighborhoodPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api != widget.api ||
        oldWidget.kind != widget.kind ||
        oldWidget.entityId != widget.entityId) {
      _rebindAndReload();
    }
  }

  @override
  void dispose() {
    authority.invalidate();
    _activeSnapshot = null;
    super.dispose();
  }

  void _rememberBinding() {
    _boundApi = widget.api;
    _boundOwner = widget.api.authenticatedUserId;
    _boundSessionVersion = widget.api.sessionVersion;
    _boundKind = widget.kind;
    _boundEntityId = widget.entityId;
  }

  bool get _bindingMatches =>
      _boundApi == widget.api &&
      _boundOwner == widget.api.authenticatedUserId &&
      _boundSessionVersion == widget.api.sessionVersion &&
      _boundKind == widget.kind &&
      _boundEntityId == widget.entityId;

  void _rebindAndReload() {
    if (_rebindScheduled) return;
    _rebindScheduled = true;
    authority.invalidate();
    _activeSnapshot = null;
    graph = null;
    error = null;
    loading = true;
    v2 = V2Api(widget.api);
    _rememberBinding();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _rebindScheduled = false;
      _load();
    });
  }

  Future<void> _load() async {
    final identity = 'graph:${widget.kind}:${widget.entityId}';
    late final V2AuthoritySnapshot snapshot;
    try {
      snapshot = authority.capture(widget.api, identity);
    } catch (exc) {
      if (!mounted) return;
      setState(() {
        loading = false;
        error = _graphErrorMessage(exc);
      });
      return;
    }
    _activeSnapshot = snapshot;
    if (mounted) {
      setState(() {
        loading = true;
        graph = null;
        error = null;
      });
    }
    try {
      final result = await v2.graphNeighborhood(
        kind: widget.kind,
        entityId: widget.entityId,
        limit: 50,
      );
      if (!mounted || !_isCurrent(snapshot, identity)) return;
      setState(() {
        graph = result;
        loading = false;
      });
    } catch (exc) {
      if (!mounted || !_isCurrent(snapshot, identity)) return;
      setState(() {
        graph = null;
        error = _graphErrorMessage(exc);
        loading = false;
      });
    }
  }

  bool _isCurrent(V2AuthoritySnapshot snapshot, String identity) {
    return _bindingMatches &&
        authority.isCurrent(widget.api, snapshot, identity);
  }

  String _graphErrorMessage(Object error) {
    if (error is ApiException) {
      if (error.statusCode == 401) return '登录状态已失效，请重新登录后再查看相关内容。';
      if (error.statusCode == 403) return '当前账号没有权限查看这些关联内容。';
      if (error.statusCode == 404) return '当前内容已不存在，无法读取关联内容。';
      return '暂时无法读取关联内容，请稍后重试。';
    }
    if (error is TransportException) return '网络暂时不可用，关联内容尚未读取。';
    if (error is ProtocolException) return '服务端返回的关联内容无法验证，已停止展示。';
    return '暂时无法读取关联内容，请稍后重试。';
  }

  void _openPerson(V2GraphNode node) {
    final snapshot = _activeSnapshot;
    final current = graph;
    final identity = 'graph:${widget.kind}:${widget.entityId}';
    if (snapshot == null ||
        current == null ||
        !_isCurrent(snapshot, identity)) {
      return;
    }
    if (!current.nodes.any((item) => item.identity == node.identity)) return;
    Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (_) => PersonDetailPage(api: widget.api, personId: node.id),
      ),
    );
  }

  Widget _stateSurface(BuildContext context) {
    final action = V3StateAction(
      label: '重试',
      onPressed: _load,
      icon: Icons.refresh,
    );
    if (error != null) {
      final variant = error!.contains('网络')
          ? V3StateSurfaceVariant.offline
          : error!.contains('权限') || error!.contains('登录')
          ? V3StateSurfaceVariant.blocked
          : V3StateSurfaceVariant.error;
      return V3StateSurface(
        key: const ValueKey('graph-error-state'),
        variant: variant,
        title: variant == V3StateSurfaceVariant.offline ? '暂时离线' : '无法显示关联内容',
        message: error!,
        primaryAction: action,
      );
    }
    return const V3StateSurface(
      key: ValueKey('graph-loading-state'),
      variant: V3StateSurfaceVariant.loading,
      title: '正在读取关联内容',
      message: '只展示当前账号有权查看的直接关联。',
    );
  }

  @override
  Widget build(BuildContext context) {
    if (!_bindingMatches) {
      _rebindAndReload();
    }
    final current = graph;
    final title = current?.center.label ?? '相关的人和事';
    return V3PageScaffold(
      topBar: V3TopBar(
        title: title,
        subtitle: current == null ? '正在确认当前账号的关联内容' : '只显示已验证的一跳关联',
        onBack: () => Navigator.of(context).maybePop(),
      ),
      child: loading || current == null
          ? _stateSurface(context)
          : _GraphView(graph: current, onPersonTap: _openPerson),
    );
  }
}

class _GraphView extends StatelessWidget {
  const _GraphView({required this.graph, required this.onPersonTap});

  final V2GraphNeighborhood graph;
  final ValueChanged<V2GraphNode> onPersonTap;

  @override
  Widget build(BuildContext context) {
    final grouped = <String, List<V2GraphNode>>{};
    for (final node in graph.nodes) {
      grouped.putIfAbsent(node.kind, () => <V2GraphNode>[]).add(node);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        V3SurfaceCard(
          key: const ValueKey('graph-center-card'),
          color: Theme.of(context).colorScheme.primaryContainer,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '当前内容',
                style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  color: Theme.of(context).colorScheme.onPrimaryContainer,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: JiYiSpacing.xs),
              Text(
                graph.center.label,
                key: const ValueKey('graph-center-label'),
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w800,
                  color: Theme.of(context).colorScheme.onPrimaryContainer,
                ),
              ),
              const SizedBox(height: JiYiSpacing.xxs),
              Text(
                _graphNodeLabel(graph.center.kind),
                style: TextStyle(
                  color: Theme.of(context).colorScheme.onPrimaryContainer,
                ),
              ),
            ],
          ),
        ),
        if (graph.truncated) ...[
          const SizedBox(height: JiYiSpacing.md),
          V3SurfaceCard(
            key: const ValueKey('graph-truncated-notice'),
            color: Theme.of(context).colorScheme.tertiaryContainer,
            semanticLabel: '仅显示部分直接关联内容',
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  Icons.info_outline,
                  color: Theme.of(context).colorScheme.onTertiaryContainer,
                ),
                const SizedBox(width: JiYiSpacing.sm),
                Expanded(
                  child: Text(
                    '仅显示部分直接关联内容。若要继续查看，请从已验证的实体详情重新发起查看。',
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.onTertiaryContainer,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
        const SizedBox(height: JiYiSpacing.xl),
        V3SectionHeader(
          title: '直接关联',
          subtitle: graph.nodes.isEmpty
              ? '当前内容暂时没有可展示的直接关联。'
              : '节点来自当前账号已验证的关系响应。',
          count: graph.nodes.length,
        ),
        const SizedBox(height: JiYiSpacing.sm),
        if (graph.nodes.isEmpty)
          const V3StateSurface(
            key: ValueKey('graph-empty-state'),
            variant: V3StateSurfaceVariant.empty,
            title: '暂时没有关联内容',
            message: '当前内容存在，但服务端没有返回可展示的一跳关系。',
          )
        else
          for (final kind in ['PERSON', 'PLACE', 'EVENT', 'OBJECT'])
            if (grouped[kind]?.isNotEmpty == true) ...[
              Padding(
                padding: const EdgeInsets.only(
                  top: JiYiSpacing.xs,
                  bottom: JiYiSpacing.xs,
                ),
                child: Text(
                  _graphNodeLabel(kind),
                  style: Theme.of(
                    context,
                  ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
              for (final node in grouped[kind]!)
                _GraphNodeCard(node: node, onPersonTap: onPersonTap),
            ],
        const SizedBox(height: JiYiSpacing.xl),
        V3SectionHeader(
          title: '关系依据',
          subtitle: graph.edges.isEmpty
              ? '当前没有可展示的关系依据。'
              : '只展示服务端返回且通过严格校验的关系。',
          count: graph.edges.length,
        ),
        const SizedBox(height: JiYiSpacing.sm),
        if (graph.edges.isEmpty)
          const V3StateSurface(
            key: ValueKey('graph-empty-edge-state'),
            variant: V3StateSurfaceVariant.empty,
            title: '没有已记录的关系',
            message: '不会根据名称、位置或文案推断新的关系。',
          )
        else
          for (final edge in graph.edges) _GraphEdgeCard(edge: edge),
      ],
    );
  }
}

class _GraphNodeCard extends StatelessWidget {
  const _GraphNodeCard({required this.node, required this.onPersonTap});

  final V2GraphNode node;
  final ValueChanged<V2GraphNode> onPersonTap;

  @override
  Widget build(BuildContext context) {
    final canOpen = node.kind == 'PERSON';
    final label = '${node.label} · ${_graphNodeLabel(node.kind)}';
    return Padding(
      padding: const EdgeInsets.only(bottom: JiYiSpacing.sm),
      child: V3SurfaceCard(
        key: ValueKey('graph-node-${node.kind}-${node.id}'),
        onTap: canOpen ? () => onPersonTap(node) : null,
        semanticLabel: canOpen ? '$label，打开人物详情' : label,
        child: Row(
          children: [
            Icon(
              canOpen ? Icons.person_outline : Icons.link_outlined,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(width: JiYiSpacing.sm),
            Expanded(
              child: Text(
                label,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(
                  context,
                ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
              ),
            ),
            if (canOpen) const Icon(Icons.chevron_right),
          ],
        ),
      ),
    );
  }
}

class _GraphEdgeCard extends StatelessWidget {
  const _GraphEdgeCard({required this.edge});

  final V2GraphEdge edge;

  String get label {
    if (edge.kind == 'PERSON_RELATIONSHIP') {
      return _relationshipLabel(
        edge.metadata.relationshipKind,
        edge.metadata.customLabel,
      );
    }
    if (edge.kind == 'PERSON_EVENT') {
      return _personMemoryRelationLabel(edge.metadata.relationKind);
    }
    return _graphEdgeKindLabel(edge.kind);
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: JiYiSpacing.sm),
      child: V3SurfaceCard(
        semanticLabel:
            '关系依据：${edge.source.label} → ${edge.target.label}，$label',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  Icons.arrow_forward,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(width: JiYiSpacing.sm),
                Expanded(
                  child: Text(
                    '${edge.source.label} → ${edge.target.label}',
                    maxLines: 4,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: JiYiSpacing.xs),
            Text(label),
            const SizedBox(height: JiYiSpacing.xxs),
            Text(
              '已记录依据 · ${_graphEdgeKindLabel(edge.kind)}',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
            if (edge.metadata.recordedAt != null) ...[
              const SizedBox(height: JiYiSpacing.xxs),
              Text(
                '记录时间：${edge.metadata.recordedAt}',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
