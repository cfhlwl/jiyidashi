import '../api_client.dart';

class TimelineReadPage {
  const TimelineReadPage({
    required this.timezone,
    required this.day,
    required this.items,
    required this.nextCursor,
  });

  final String timezone;
  final String? day;
  final List<TimelineReadItem> items;
  final String? nextCursor;

  factory TimelineReadPage.parse(Map<String, dynamic> raw) {
    final timezone = _requiredText(raw['timezone'], '时间线时区', max: 64);
    final day = raw['day'];
    if (day != null &&
        (day is! String ||
            !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(day) ||
            DateTime.tryParse(day) == null)) {
      throw ProtocolException('时间线数据格式不正确');
    }

    final rawItems = raw['items'];
    if (rawItems is! List<dynamic> || rawItems.length > 100) {
      throw ProtocolException('时间线数据格式不正确');
    }
    final items = rawItems
        .map(TimelineReadItem.parse)
        .toList(growable: false);

    final rawCursor = raw['next_cursor'];
    String? nextCursor;
    if (rawCursor != null) {
      if (rawCursor is! String ||
          rawCursor.isEmpty ||
          rawCursor.length > 4096) {
        throw ProtocolException('时间线数据格式不正确');
      }
      nextCursor = rawCursor;
    }

    return TimelineReadPage(
      timezone: timezone,
      day: day as String?,
      items: List.unmodifiable(items),
      nextCursor: nextCursor,
    );
  }
}

class TimelineReadItem {
  const TimelineReadItem({
    required this.kind,
    required this.id,
    required this.occurredAt,
    required this.endedAt,
    required this.placeId,
    required this.placeName,
    required this.memoryType,
    required this.title,
    required this.content,
    required this.isConfirmed,
    required this.confidence,
    required this.visitFinalized,
  });

  final String kind;
  final String id;
  final String occurredAt;
  final String? endedAt;
  final String? placeId;
  final String? placeName;
  final String? memoryType;
  final String? title;
  final String? content;
  final bool? isConfirmed;
  final double confidence;
  final bool? visitFinalized;

  bool get isMemory => kind == 'MEMORY';
  bool get isVisit => kind == 'VISIT';

  factory TimelineReadItem.parse(Object? value) {
    if (value is! Map<String, dynamic>) {
      throw ProtocolException('时间线记录格式不正确');
    }
    final kind = value['kind'];
    if (kind != 'MEMORY' && kind != 'VISIT') {
      throw ProtocolException('时间线记录格式不正确');
    }

    final id = _uuid(value['id'], '时间线记录');
    final occurredAt = _aware(value['occurred_at'], '时间线记录');
    final endedAt = value['ended_at'] == null
        ? null
        : _aware(value['ended_at'], '时间线记录');
    if (endedAt != null &&
        DateTime.parse(endedAt).toUtc().isBefore(
              DateTime.parse(occurredAt).toUtc(),
            )) {
      throw ProtocolException('时间线记录格式不正确');
    }

    final confidenceRaw = value['confidence'];
    if (confidenceRaw is! num ||
        !confidenceRaw.toDouble().isFinite ||
        confidenceRaw < 0 ||
        confidenceRaw > 1) {
      throw ProtocolException('时间线记录格式不正确');
    }

    final placeId = value['place_id'] == null
        ? null
        : _uuid(value['place_id'], '时间线地点');
    final placeName = _nullableText(value['place_name'], max: 200);
    final memoryType = _nullableText(value['memory_type'], max: 80);
    final title = _nullableText(value['title'], max: 240);
    final content = _nullableText(value['content'], max: 20000);
    final isConfirmed = value['is_confirmed'];
    final visitFinalized = value['visit_finalized'];

    if (kind == 'MEMORY') {
      if (memoryType == null ||
          content == null ||
          isConfirmed is! bool ||
          visitFinalized != null) {
        throw ProtocolException('时间线记录格式不正确');
      }
    } else {
      if (placeId == null ||
          placeName == null ||
          visitFinalized is! bool ||
          memoryType != null ||
          title != null ||
          content != null ||
          isConfirmed != null) {
        throw ProtocolException('时间线记录格式不正确');
      }
    }

    return TimelineReadItem(
      kind: kind,
      id: id,
      occurredAt: occurredAt,
      endedAt: endedAt,
      placeId: placeId,
      placeName: placeName,
      memoryType: memoryType,
      title: title,
      content: content,
      isConfirmed: isConfirmed as bool?,
      confidence: confidenceRaw.toDouble(),
      visitFinalized: visitFinalized as bool?,
    );
  }
}

final RegExp _uuidRe = RegExp(
  r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
  caseSensitive: false,
);

String _uuid(Object? value, String label) {
  if (value is! String || !_uuidRe.hasMatch(value)) {
    throw ProtocolException('$label 数据格式不正确');
  }
  return value;
}

String _aware(Object? value, String label) {
  if (value is! String ||
      !RegExp(r'(?:Z|[+-]\d{2}:\d{2})$').hasMatch(value) ||
      DateTime.tryParse(value) == null) {
    throw ProtocolException('$label 数据格式不正确');
  }
  return value;
}

String _requiredText(Object? value, String label, {int max = 5000}) {
  if (value is! String || value.trim().isEmpty || value.length > max) {
    throw ProtocolException('$label 数据格式不正确');
  }
  return value.trim();
}

String? _nullableText(Object? value, {int max = 5000}) {
  if (value == null) return null;
  if (value is! String || value.trim().isEmpty || value.length > max) {
    throw ProtocolException('时间线记录格式不正确');
  }
  return value.trim();
}
