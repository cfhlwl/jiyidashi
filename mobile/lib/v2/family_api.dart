import '../api_client.dart';
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
