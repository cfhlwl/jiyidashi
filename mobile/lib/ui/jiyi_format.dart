String jiyiDisplayDate(String value, {String fallback = '时间未知'}) {
  final parsed = DateTime.tryParse(value);
  if (parsed == null) return fallback;
  final local = parsed.toLocal();
  return '${local.year}年${local.month}月${local.day}日';
}

String jiyiDisplayDateTime(String value, {String fallback = '时间未知'}) {
  final parsed = DateTime.tryParse(value);
  if (parsed == null) return fallback;
  final local = parsed.toLocal();
  String two(int value) => value.toString().padLeft(2, '0');
  return '${local.year}年${local.month}月${local.day}日 '
      '${two(local.hour)}:${two(local.minute)}';
}

String jiyiDisplayTime(String value, {String fallback = '时间未知'}) {
  final parsed = DateTime.tryParse(value);
  if (parsed == null) return fallback;
  final local = parsed.toLocal();
  String two(int value) => value.toString().padLeft(2, '0');
  return '${two(local.hour)}:${two(local.minute)}';
}

String jiyiDisplayDateRange(
  String start,
  String? end, {
  String openEnded = '至今',
}) {
  final startText = jiyiDisplayDate(start);
  if (end == null || end.trim().isEmpty) return '$startText – $openEnded';
  return '$startText – ${jiyiDisplayDate(end)}';
}
