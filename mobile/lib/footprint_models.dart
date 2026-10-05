class FootprintDay {
  const FootprintDay({
    required this.timezone,
    required this.day,
    required this.visits,
  });

  final String timezone;
  final String day;
  final List<FootprintVisit> visits;

  factory FootprintDay.fromJson(Map<String, dynamic> data) {
    final timezone = data['timezone'];
    final day = data['day'];
    final visits = data['visits'];
    if (timezone is! String ||
        timezone.trim().isEmpty ||
        day is! String ||
        !isStrictDateOnly(day) ||
        visits is! List<dynamic>) {
      throw const FormatException('invalid footprint day');
    }
    return FootprintDay(
      timezone: timezone,
      day: day,
      visits: visits
          .map((item) {
            if (item is! Map<String, dynamic>) {
              throw const FormatException('invalid footprint visit');
            }
            return FootprintVisit.fromJson(item);
          })
          .toList(growable: false),
    );
  }

  List<FootprintVisit> get mappableVisits =>
      visits.where((visit) => visit.isMappable).toList(growable: false);
}

class FootprintVisit {
  const FootprintVisit({
    required this.id,
    required this.placeId,
    required this.placeName,
    required this.latitude,
    required this.longitude,
    required this.address,
    required this.category,
    required this.arrivedAt,
    required this.leftAt,
    required this.arrivedAtLocal,
    required this.leftAtLocal,
    required this.confidence,
    required this.visitSource,
    required this.finalized,
  });

  final String id;
  final String placeId;
  final String placeName;
  final double? latitude;
  final double? longitude;
  final String? address;
  final String? category;
  final String arrivedAt;
  final String? leftAt;
  final String arrivedAtLocal;
  final String? leftAtLocal;
  final double confidence;
  final String visitSource;
  final bool finalized;

  bool get isMappable => latitude != null && longitude != null;

  factory FootprintVisit.fromJson(Map<String, dynamic> data) {
    final id = data['id'];
    final placeId = data['place_id'];
    final placeName = data['place_name'];
    final latitude = data['place_latitude'];
    final longitude = data['place_longitude'];
    final address = data['place_address'];
    final category = data['place_category'];
    final arrivedAt = data['arrived_at'];
    final leftAt = data['left_at'];
    final arrivedAtLocal = data['arrived_at_local'];
    final leftAtLocal = data['left_at_local'];
    final confidence = data['confidence'];
    final visitSource = data['visit_source'];
    final finalized = data['visit_finalized'];

    if (id is! String ||
        id.trim().isEmpty ||
        placeId is! String ||
        placeId.trim().isEmpty ||
        placeName is! String ||
        placeName.trim().isEmpty ||
        arrivedAt is! String ||
        arrivedAt.trim().isEmpty ||
        (leftAt != null && leftAt is! String) ||
        arrivedAtLocal is! String ||
        arrivedAtLocal.trim().isEmpty ||
        (leftAtLocal != null && leftAtLocal is! String) ||
        confidence is! num ||
        !confidence.isFinite ||
        visitSource is! String ||
        visitSource.trim().isEmpty ||
        finalized is! bool ||
        (address != null && address is! String) ||
        (category != null && category is! String)) {
      throw const FormatException('invalid footprint visit');
    }

    final parsedLatitude = _optionalCoordinate(latitude, latitudeAxis: true);
    final parsedLongitude = _optionalCoordinate(longitude, latitudeAxis: false);
    if ((parsedLatitude == null) != (parsedLongitude == null)) {
      throw const FormatException('partial footprint coordinate');
    }

    if (!isStrictIsoDateTime(arrivedAt) ||
        (leftAt is String && !isStrictIsoDateTime(leftAt)) ||
        !isStrictIsoDateTime(arrivedAtLocal) ||
        (leftAtLocal is String && !isStrictIsoDateTime(leftAtLocal))) {
      throw const FormatException('invalid footprint visit');
    }

    return FootprintVisit(
      id: id,
      placeId: placeId,
      placeName: placeName.trim(),
      latitude: parsedLatitude,
      longitude: parsedLongitude,
      address: address is String && address.trim().isNotEmpty
          ? address.trim()
          : null,
      category: category is String && category.trim().isNotEmpty
          ? category.trim()
          : null,
      arrivedAt: arrivedAt,
      leftAt: leftAt as String?,
      arrivedAtLocal: arrivedAtLocal,
      leftAtLocal: leftAtLocal as String?,
      confidence: confidence.toDouble(),
      visitSource: visitSource,
      finalized: finalized,
    );
  }
}

double? _optionalCoordinate(Object? value, {required bool latitudeAxis}) {
  if (value == null) return null;
  if (value is! num || !value.isFinite) {
    throw const FormatException('invalid footprint coordinate');
  }
  final result = value.toDouble();
  final max = latitudeAxis ? 90.0 : 180.0;
  if (result < -max || result > max) {
    throw const FormatException('invalid footprint coordinate');
  }
  return result;
}

bool isStrictDateOnly(String value) {
  final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch(value);
  if (match == null) return false;
  final year = int.parse(match.group(1)!);
  final month = int.parse(match.group(2)!);
  final day = int.parse(match.group(3)!);
  final parsed = DateTime.utc(year, month, day);
  return parsed.year == year && parsed.month == month && parsed.day == day;
}

bool isStrictIsoDateTime(String value) {
  final match = RegExp(
    r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$',
  ).firstMatch(value);
  if (match == null || !isStrictDateOnly(value.substring(0, 10))) return false;
  final hour = int.parse(match.group(4)!);
  final minute = int.parse(match.group(5)!);
  final second = int.parse(match.group(6)!);
  if (hour > 23 || minute > 59 || second > 59) return false;
  return DateTime.tryParse(value) != null;
}
