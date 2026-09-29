import '../api_client.dart';

final RegExp _uuidRe = RegExp(
  r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
  caseSensitive: false,
);
final RegExp _awareRe = RegExp(r'(?:Z|[+-][0-9]{2}:[0-9]{2})$');
final RegExp _yearRe = RegExp(r'^[0-9]{4}$');

Never v2Invalid([String label = 'V2']) {
  throw ProtocolException(label + ' 数据格式不正确');
}

Map<String, dynamic> v2Map(Object? value, [String label = 'V2']) {
  if (value is! Map<String, dynamic>) return v2Invalid(label);
  return value;
}

List<dynamic> v2List(Object? value, [String label = 'V2', int max = 100]) {
  if (value is! List<dynamic> || value.length > max) return v2Invalid(label);
  return value;
}

String v2Text(
  Object? value, {
  String label = 'V2',
  int max = 5000,
  bool trim = true,
}) {
  if (value is! String) return v2Invalid(label);
  final result = trim ? value.trim() : value;
  if (result.isEmpty || result.length > max) return v2Invalid(label);
  return result;
}

String? v2NullableText(
  Object? value, {
  String label = 'V2',
  int max = 5000,
  bool allowEmpty = false,
}) {
  if (value == null) return null;
  if (value is! String || value.length > max) return v2Invalid(label);
  if (!allowEmpty && value.trim().isEmpty) return v2Invalid(label);
  return value;
}

String v2Uuid(Object? value, [String label = 'V2']) {
  if (value is! String || !_uuidRe.hasMatch(value)) return v2Invalid(label);
  return value;
}

String? v2NullableUuid(Object? value, [String label = 'V2']) {
  if (value == null) return null;
  return v2Uuid(value, label);
}

String v2Aware(Object? value, [String label = 'V2']) {
  if (value is! String ||
      !_awareRe.hasMatch(value) ||
      DateTime.tryParse(value) == null) {
    return v2Invalid(label);
  }
  return value;
}

String? v2NullableAware(Object? value, [String label = 'V2']) {
  if (value == null) return null;
  return v2Aware(value, label);
}

int v2Int(
  Object? value, {
  String label = 'V2',
  int min = 0,
  int max = 9007199254740991,
}) {
  if (value is! int || value < min || value > max) return v2Invalid(label);
  return value;
}

int? v2NullableInt(
  Object? value, {
  String label = 'V2',
  int min = 0,
}) {
  if (value == null) return null;
  return v2Int(value, label: label, min: min);
}

double v2Double(Object? value, [String label = 'V2']) {
  if (value is! num || !value.toDouble().isFinite) return v2Invalid(label);
  return value.toDouble();
}

bool v2Bool(Object? value, [String label = 'V2']) {
  if (value is! bool) return v2Invalid(label);
  return value;
}

String v2Enum(Object? value, Set<String> allowed, [String label = 'V2']) {
  if (value is! String || !allowed.contains(value)) return v2Invalid(label);
  return value;
}

String v2Cursor(Object? value, [String label = 'V2']) {
  if (value is! String || value.isEmpty || value.length > 4096) {
    return v2Invalid(label);
  }
  return value;
}

String? v2NullableCursor(Object? value, [String label = 'V2']) {
  if (value == null) return null;
  return v2Cursor(value, label);
}

String v2Year(Object? value, [String label = 'V2']) {
  if (value is! String || !_yearRe.hasMatch(value)) return v2Invalid(label);
  final year = int.tryParse(value);
  if (year == null || year < 1 || year > 9998) return v2Invalid(label);
  return value;
}

List<String> v2StringList(
  Object? value, {
  String label = 'V2',
  int maxItems = 100,
  int maxText = 200,
  bool unique = true,
}) {
  final raw = v2List(value, label, maxItems);
  final result = <String>[];
  final seen = <String>{};
  for (final item in raw) {
    final parsed = v2Text(item, label: label, max: maxText);
    if (unique && !seen.add(parsed.toLowerCase())) return v2Invalid(label);
    result.add(parsed);
  }
  return List.unmodifiable(result);
}

const Set<String> answerTrustStates = {
  'CONFIRMED',
  'EVIDENCE_SUPPORTED',
  'INFERENCE_ONLY',
  'NO_EVIDENCE',
};

const Set<String> citationTrustStates = {
  'CONFIRMED',
  'EVIDENCE_SUPPORTED',
};

String v2AnswerTrust(Object? value, [String label = 'V2']) =>
    v2Enum(value, answerTrustStates, label);

String? v2NullableAnswerTrust(Object? value, [String label = 'V2']) {
  if (value == null) return null;
  return v2AnswerTrust(value, label);
}

String v2CitationTrust(Object? value, [String label = 'V2']) =>
    v2Enum(value, citationTrustStates, label);

String? v2NullableCitationTrust(Object? value, [String label = 'V2']) {
  if (value == null) return null;
  return v2CitationTrust(value, label);
}

void v2UniqueSlots(
  Iterable<String> slots, {
  String label = 'V2 引用',
}) {
  final seen = <String>{};
  for (final slot in slots) {
    final normalized = slot.trim();
    if (!seen.add(normalized)) return v2Invalid(label);
  }
}

bool v2SameInstant(String left, String right) {
  final a = DateTime.parse(left);
  final b = DateTime.parse(right);
  return a.toUtc() == b.toUtc();
}

String v2PathId(String id, [String label = 'V2']) {
  v2Uuid(id, label);
  return Uri.encodeComponent(id);
}
