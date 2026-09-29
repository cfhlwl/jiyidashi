import '../api_client.dart';
import 'v2_common.dart';

const Set<String> familyRoles = {'OWNER', 'MEMBER'};

const String familyViewCurrentLocation = 'VIEW_CURRENT_LOCATION';
const String familyViewFootprint = 'VIEW_FOOTPRINT';
const String familyViewMemory = 'VIEW_MEMORY';
const String familyViewPhotos = 'VIEW_PHOTOS';

const List<String> interactiveFamilyPermissions = <String>[
  familyViewMemory,
  familyViewPhotos,
  familyViewFootprint,
  familyViewCurrentLocation,
];

class V2FamilyMember {
  const V2FamilyMember({
    required this.userId,
    required this.role,
    required this.createdAt,
  });

  final String userId;
  final String role;
  final String createdAt;

  factory V2FamilyMember.parse(Object? value) {
    final raw = v2Map(value, '家庭成员');
    return V2FamilyMember(
      userId: v2Uuid(raw['user_id'], '家庭成员'),
      role: v2Enum(raw['role'], familyRoles, '家庭成员'),
      createdAt: v2Aware(raw['created_at'], '家庭成员'),
    );
  }
}

class V2Family {
  const V2Family({
    required this.familyId,
    required this.currentUserRole,
    required this.members,
  });

  final String familyId;
  final String currentUserRole;
  final List<V2FamilyMember> members;

  factory V2Family.parse(Object? value, {required String currentUserId}) {
    final raw = v2Map(value, '家庭');
    final members = v2List(raw['members'], '家庭成员', 100)
        .map(V2FamilyMember.parse)
        .toList(growable: false);
    if (members.isEmpty) return v2Invalid('家庭成员');
    final ids = <String>{};
    for (final member in members) {
      if (!ids.add(member.userId.toLowerCase())) return v2Invalid('家庭成员');
    }
    if (members.where((item) => item.role == 'OWNER').length != 1) {
      return v2Invalid('家庭成员');
    }
    final currentRole = v2Enum(raw['current_user_role'], familyRoles, '家庭');
    final current = members.where(
      (item) => item.userId.toLowerCase() == currentUserId.toLowerCase(),
    );
    if (current.length != 1 || current.single.role != currentRole) {
      return v2Invalid('家庭');
    }
    return V2Family(
      familyId: v2Uuid(raw['family_id'], '家庭'),
      currentUserRole: currentRole,
      members: List.unmodifiable(members),
    );
  }
}

class V2FamilyPermissionGrant {
  const V2FamilyPermissionGrant({
    required this.granteeUserId,
    required this.permissions,
  });

  final String granteeUserId;
  final List<String> permissions;

  factory V2FamilyPermissionGrant.parse(Object? value) {
    final raw = v2Map(value, '家庭权限');
    final rawPermissions = raw['permissions'];
    if (rawPermissions is! List) return v2Invalid('家庭权限');
    if (rawPermissions.length > 100) return v2Invalid('家庭权限');
    final permissions = <String>[];
    final seen = <String>{};
    for (final item in rawPermissions) {
      if (item is! String || item.trim().isEmpty || item.length > 80) {
        return v2Invalid('家庭权限');
      }
      if (!seen.add(item)) return v2Invalid('家庭权限');
      permissions.add(item);
    }
    return V2FamilyPermissionGrant(
      granteeUserId: v2Uuid(raw['grantee_user_id'], '家庭权限'),
      permissions: List.unmodifiable(permissions),
    );
  }

  V2FamilyPermissionGrant toggle(String code, bool enabled) {
    if (!interactiveFamilyPermissions.contains(code)) {
      throw ArgumentError('不支持的家庭权限');
    }
    final next = permissions.where((item) => item != code).toList(growable: true);
    if (enabled) next.add(code);
    return V2FamilyPermissionGrant(
      granteeUserId: granteeUserId,
      permissions: List.unmodifiable(next),
    );
  }

  bool has(String code) => permissions.contains(code);
}

List<V2FamilyPermissionGrant> parseFamilyPermissions(Object? value) {
  final rows = v2List(value, '家庭权限', 100)
      .map(V2FamilyPermissionGrant.parse)
      .toList(growable: false);
  final ids = <String>{};
  for (final row in rows) {
    if (!ids.add(row.granteeUserId.toLowerCase())) return v2Invalid('家庭权限');
  }
  return List.unmodifiable(rows);
}

class V2FamilyInvite {
  const V2FamilyInvite({
    required this.inviteId,
    required this.token,
    required this.expiresAt,
  });

  final String inviteId;
  final String token;
  final String expiresAt;

  factory V2FamilyInvite.parse(Object? value) {
    final raw = v2Map(value, '家庭邀请');
    final token = v2Text(raw['token'], label: '家庭邀请', max: 512);
    return V2FamilyInvite(
      inviteId: v2Uuid(raw['invite_id'], '家庭邀请'),
      token: token,
      expiresAt: v2Aware(raw['expires_at'], '家庭邀请'),
    );
  }
}

String shortFamilyMemberId(String userId) {
  if (userId.length < 9) return '家庭成员';
  return userId.substring(0, 4) + '…' + userId.substring(userId.length - 4);
}

String familyRoleLabel(String role) => role == 'OWNER' ? '家庭创建者' : '家庭成员';

String familyPermissionLabel(String code) => switch (code) {
      familyViewMemory => '可查看我的记忆',
      familyViewPhotos => '可查看我的照片',
      familyViewFootprint => '可查看我的今日足迹',
      familyViewCurrentLocation => '可查看我的当前位置',
      _ => '其他授权',
    };
