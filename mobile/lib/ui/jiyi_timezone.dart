import 'package:timezone/data/latest.dart' as timezone_data;
import 'package:timezone/timezone.dart' as timezone;

bool _initialized = false;

void _ensureTimezoneData() {
  if (_initialized) return;
  timezone_data.initializeTimeZones();
  _initialized = true;
}

/// Converts a server UTC/offset timestamp into the account's server-owned
/// IANA timezone. Returning a TZDateTime keeps the wall-clock fields stable
/// for UI grouping and display without consulting the device timezone.
DateTime? jiyiDateTimeInTimezone(String value, String timezoneName) {
  final instant = DateTime.tryParse(value);
  if (instant == null) return null;
  try {
    _ensureTimezoneData();
    final location = timezone.getLocation(timezoneName);
    return timezone.TZDateTime.from(instant.toUtc(), location);
  } on Object {
    return null;
  }
}
