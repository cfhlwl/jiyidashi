import '../api_client.dart';
import '../footprint_models.dart';
import 'family_models.dart';

class FamilyApi {
  FamilyApi(this.api);

  final JiYiApiClient api;

  Future<Object?> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) =>
      api.requestV2Json(method, path, body: body);

  String get currentUserId {
    final value = api.authenticatedUserId?.trim();
    if (value == null || value.isEmpty) throw ApiException(401, '请先登录');
    return value;
  }

  Future<V2Family> getFamily() async {
    return V2Family.parse(
      await _request('GET', '/family'),
      currentUserId: currentUserId,
    );
  }

  Future<V2Family> createFamily() async {
    return V2Family.parse(
      await _request('POST', '/family'),
      currentUserId: currentUserId,
    );
  }

  Future<V2Family> acceptInvite(String token) async {
    final normalized = token.trim();
    if (normalized.isEmpty || normalized.length > 512) {
      throw ArgumentError('请输入有效的家庭邀请口令');
    }
    return V2Family.parse(
      await _request(
        'POST',
        '/family/invites/accept',
        body: {'token': normalized},
      ),
      currentUserId: currentUserId,
    );
  }

  Future<V2FamilyInvite> createInvite() async {
    return V2FamilyInvite.parse(await _request('POST', '/family/invites'));
  }

  Future<List<V2FamilyPermissionGrant>> listPermissions() async {
    return parseFamilyPermissions(await _request('GET', '/family/permissions'));
  }

  Future<V2FamilyCurrentLocation> getMemberCurrentLocation(
    String resourceOwnerUserId,
  ) async {
    final owner = v2PathId(resourceOwnerUserId, '家庭成员');
    return V2FamilyCurrentLocation.parse(
      await _request('GET', '/family/members/$owner/current-location'),
      expectedResourceOwnerUserId: resourceOwnerUserId,
    );
  }

  Future<FootprintDay> getMemberTodayFootprint(String resourceOwnerUserId) async {
    final owner = v2PathId(resourceOwnerUserId, '家庭成员');
    final raw = await _request('GET', '/family/members/$owner/today/footprint');
    try {
      return FootprintDay.fromJson(v2Map(raw, '家庭足迹'));
    } on FormatException {
      throw ProtocolException('家庭足迹数据格式不正确');
    }
  }

  Future<List<V2FamilyMemory>> getMemberMemories(
    String resourceOwnerUserId, {
    int limit = 8,
  }) async {
    if (limit < 1 || limit > 50) {
      throw ArgumentError.value(limit, 'limit', 'must be 1..50');
    }
    final owner = v2PathId(resourceOwnerUserId, '家庭成员');
    return parseFamilyMemories(
      await _request('GET', '/family/members/$owner/memories?limit=$limit'),
    );
  }

  Future<List<V2FamilyPhoto>> getMemberPhotos(
    String resourceOwnerUserId,
  ) async {
    final owner = v2PathId(resourceOwnerUserId, '家庭成员');
    return parseFamilyPhotos(
      await _request('GET', '/family/members/$owner/photos'),
    );
  }

  Future<V2FamilyPhotoDownload> createMemberPhotoDownload(
    String resourceOwnerUserId,
    String mediaId,
  ) async {
    final owner = v2PathId(resourceOwnerUserId, '家庭成员');
    final media = v2PathId(mediaId, '家庭照片');
    return V2FamilyPhotoDownload.parse(
      await _request(
        'POST',
        '/family/members/$owner/photos/$media/download',
      ),
      expectedMediaId: mediaId,
    );
  }

  Future<V2FamilyPermissionGrant> replacePermissions(
    V2FamilyPermissionGrant grant,
  ) async {
    final raw = await _request(
      'PUT',
      '/family/permissions/${grant.granteeUserId}',
      body: {'permissions': grant.permissions},
    );
    final parsed = V2FamilyPermissionGrant.parse(raw);
    if (parsed.granteeUserId.toLowerCase() != grant.granteeUserId.toLowerCase()) {
      throw ProtocolException('家庭权限返回对象不匹配');
    }
    return parsed;
  }
}
