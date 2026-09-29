import 'people_models.dart';
import 'v2_common.dart';

const Set<String> graphNodeKinds = {'PERSON', 'PLACE', 'OBJECT', 'EVENT'};
const Set<String> graphEdgeKinds = {
  'PERSON_RELATIONSHIP',
  'PERSON_EVENT',
  'OBJECT_PLACE',
  'EVENT_PLACE',
};

class V2GraphNode {
  const V2GraphNode({
    required this.kind,
    required this.id,
    required this.label,
    required this.occurredAt,
  });

  final String kind;
  final String id;
  final String label;
  final String? occurredAt;

  String get identity => kind + ':' + id.toLowerCase();

  factory V2GraphNode.parse(Object? value) {
    final raw = v2Map(value, '图谱节点');
    return V2GraphNode(
      kind: v2Enum(raw['kind'], graphNodeKinds, '图谱节点'),
      id: v2Uuid(raw['id'], '图谱节点'),
      label: v2Text(raw['label'], label: '图谱节点', max: 500),
      occurredAt: v2NullableAware(raw['occurred_at'], '图谱节点'),
    );
  }

  bool sameProjection(V2GraphNode other) =>
      kind == other.kind &&
      id.toLowerCase() == other.id.toLowerCase() &&
      label == other.label &&
      occurredAt == other.occurredAt;
}

class V2GraphEdgeMetadata {
  const V2GraphEdgeMetadata({
    required this.relationshipKind,
    required this.customLabel,
    required this.relationKind,
    required this.recordedAt,
  });

  final String? relationshipKind;
  final String? customLabel;
  final String? relationKind;
  final String? recordedAt;

  factory V2GraphEdgeMetadata.parse(Object? value) {
    final raw = v2Map(value, '图谱边');
    return V2GraphEdgeMetadata(
      relationshipKind: v2NullableText(
        raw['relationship_kind'],
        label: '图谱边',
        max: 120,
      ),
      customLabel: v2NullableText(
        raw['custom_label'],
        label: '图谱边',
        max: 120,
      ),
      relationKind: v2NullableText(
        raw['relation_kind'],
        label: '图谱边',
        max: 120,
      ),
      recordedAt: v2NullableAware(raw['recorded_at'], '图谱边'),
    );
  }
}

class V2GraphEdge {
  const V2GraphEdge({
    required this.kind,
    required this.source,
    required this.target,
    required this.authorityRef,
    required this.metadata,
  });

  final String kind;
  final V2GraphNode source;
  final V2GraphNode target;
  final String authorityRef;
  final V2GraphEdgeMetadata metadata;

  factory V2GraphEdge.parse(Object? value) {
    final raw = v2Map(value, '图谱边');
    final source = V2GraphNode.parse(raw['source']);
    final target = V2GraphNode.parse(raw['target']);
    if (source.identity == target.identity) return v2Invalid('图谱边');
    final kind = v2Enum(raw['edge_kind'], graphEdgeKinds, '图谱边');
    final metadata = V2GraphEdgeMetadata.parse(raw['metadata']);

    final endpointKinds = {source.kind, target.kind};
    if (kind == 'PERSON_RELATIONSHIP') {
      if (endpointKinds.length != 1 ||
          !endpointKinds.contains('PERSON') ||
          metadata.relationshipKind == null ||
          !relationshipKinds.contains(metadata.relationshipKind) ||
          metadata.relationKind != null ||
          metadata.recordedAt != null) {
        return v2Invalid('图谱边');
      }
      if (metadata.relationshipKind == 'OTHER'
          ? (metadata.customLabel == null ||
              metadata.customLabel!.trim().isEmpty)
          : metadata.customLabel != null) {
        return v2Invalid('图谱边');
      }
    } else if (kind == 'PERSON_EVENT') {
      if (endpointKinds.length != 2 ||
          !endpointKinds.contains('PERSON') ||
          !endpointKinds.contains('EVENT') ||
          metadata.relationKind == null ||
          !personMemoryRelationKinds.contains(metadata.relationKind) ||
          metadata.relationshipKind != null ||
          metadata.customLabel != null ||
          metadata.recordedAt != null) {
        return v2Invalid('图谱边');
      }
    } else if (kind == 'OBJECT_PLACE') {
      if (endpointKinds.length != 2 ||
          !endpointKinds.contains('OBJECT') ||
          !endpointKinds.contains('PLACE') ||
          metadata.recordedAt == null ||
          metadata.relationshipKind != null ||
          metadata.customLabel != null ||
          metadata.relationKind != null) {
        return v2Invalid('图谱边');
      }
    } else if (endpointKinds.length != 2 ||
        !endpointKinds.contains('EVENT') ||
        !endpointKinds.contains('PLACE') ||
        metadata.relationshipKind != null ||
        metadata.customLabel != null ||
        metadata.relationKind != null ||
        metadata.recordedAt != null) {
      return v2Invalid('图谱边');
    }

    return V2GraphEdge(
      kind: kind,
      source: source,
      target: target,
      authorityRef: v2Uuid(raw['authority_ref'], '图谱边'),
      metadata: metadata,
    );
  }
}

class V2GraphNeighborhood {
  const V2GraphNeighborhood({
    required this.center,
    required this.nodes,
    required this.edges,
    required this.truncated,
  });

  final V2GraphNode center;
  final List<V2GraphNode> nodes;
  final List<V2GraphEdge> edges;
  final bool truncated;

  factory V2GraphNeighborhood.parse(
    Object? value, {
    required String expectedKind,
    required String expectedId,
  }) {
    final raw = v2Map(value, '关系图谱');
    final center = V2GraphNode.parse(raw['center']);
    if (center.kind != expectedKind ||
        center.id.toLowerCase() != expectedId.toLowerCase()) {
      return v2Invalid('关系图谱');
    }
    final nodeList = v2List(raw['nodes'], '关系图谱', 100)
        .map(V2GraphNode.parse)
        .toList(growable: false);
    final registry = <String, V2GraphNode>{center.identity: center};
    for (final node in nodeList) {
      if (registry.containsKey(node.identity)) return v2Invalid('关系图谱');
      registry[node.identity] = node;
    }
    final edgeList = v2List(raw['edges'], '关系图谱', 300)
        .map(V2GraphEdge.parse)
        .toList(growable: false);
    final authorityRefs = <String>{};
    for (final edge in edgeList) {
      final source = registry[edge.source.identity];
      final target = registry[edge.target.identity];
      if (source == null ||
          target == null ||
          !source.sameProjection(edge.source) ||
          !target.sameProjection(edge.target) ||
          !authorityRefs.add(edge.authorityRef.toLowerCase())) {
        return v2Invalid('关系图谱');
      }
    }
    return V2GraphNeighborhood(
      center: center,
      nodes: List.unmodifiable(nodeList),
      edges: List.unmodifiable(edgeList),
      truncated: v2Bool(raw['truncated'], '关系图谱'),
    );
  }
}
