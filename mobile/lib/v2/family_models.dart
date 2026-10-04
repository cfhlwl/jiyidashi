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

class V2FamilyCurrentLocation {
  const V2FamilyCurrentLocation({
    required this.resourceOwnerUserId,
    required this.latitude,
    required this.longitude,
    required this.accuracy,
    required this.recordedAt,
    required this.freshUntil,
  });

  final String resourceOwnerUserId;
  final double latitude;
  final double longitude;
  final double? accuracy;
  final String recordedAt;
  final String freshUntil;

  factory V2FamilyCurrentLocation.parse(
    Object? value, {
    required String expectedResourceOwnerUserId,
  }) {
    final raw = v2Map(value, '家庭当前位置');
    final owner = v2Uuid(raw['resource_owner_user_id'], '家庭当前位置');
    if (owner.toLowerCase() != expectedResourceOwnerUserId.toLowerCase()) {
      return v2Invalid('家庭当前位置');
    }
    final latitude = v2Double(raw['latitude'], '家庭当前位置');
    final longitude = v2Double(raw['longitude'], '家庭当前位置');
    if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
      return v2Invalid('家庭当前位置');
    }
    final rawAccuracy = raw['accuracy'];
    final accuracy = rawAccuracy == null
        ? null
        : v2Double(rawAccuracy, '家庭当前位置');
    if (accuracy != null && accuracy < 0) return v2Invalid('家庭当前位置');
    final recordedAt = v2Aware(raw['recorded_at'], '家庭当前位置');
    final freshUntil = v2Aware(raw['fresh_until'], '家庭当前位置');
    if (DateTime.parse(freshUntil).toUtc().isBefore(
          DateTime.parse(recordedAt).toUtc(),
        )) {
      return v2Invalid('家庭当前位置');
    }
    return V2FamilyCurrentLocation(
      resourceOwnerUserId: owner,
      latitude: latitude,
      longitude: longitude,
      accuracy: accuracy,
      recordedAt: recordedAt,
      freshUntil: freshUntil,
    );
  }
}

class V2FamilyMemory {
  const V2FamilyMemory({
    required this.memoryId,
    required this.memoryType,
    required this.title,
    required this.content,
    required this.occurredAt,
    required this.sourceType,
    required this.isConfirmed,
    required this.editRevision,
    required this.createdAt,
  });

  final String memoryId;
  final String memoryType;
  final String? title;
  final String content;
  final String occurredAt;
  final String sourceType;
  final bool isConfirmed;
  final int editRevision;
  final String createdAt;

  factory V2FamilyMemory.parse(Object? value) {
    final raw = v2Map(value, '家庭记忆');
    final title = raw['title'];
    if (title != null && (title is! String || title.length > 240)) {
      return v2Invalid('家庭记忆');
    }
    final content = raw['content'];
    if (content is! String || content.length > 20000) {
      return v2Invalid('家庭记忆');
    }
    return V2FamilyMemory(
      memoryId: v2Uuid(raw['memory_id'], '家庭记忆'),
      memoryType: v2Text(raw['memory_type'], label: '家庭记忆', max: 40),
      title: title as String?,
      content: content,
      occurredAt: v2Aware(raw['occurred_at'], '家庭记忆'),
      sourceType: v2Text(raw['source_type'], label: '家庭记忆', max: 80),
      isConfirmed: v2Bool(raw['is_confirmed'], '家庭记忆'),
      editRevision: v2Int(raw['edit_revision'], label: '家庭记忆'),
      createdAt: v2Aware(raw['created_at'], '家庭记忆'),
    );
  }
}

class V2FamilyPhoto {
  const V2FamilyPhoto({
    required this.mediaId,
    required this.contentType,
    required this.sizeBytes,
    required this.createdAt,
    required this.completedAt,
    required this.cacheVersion,
  });

  final String mediaId;
  final String contentType;
  final int sizeBytes;
  final String createdAt;
  final String completedAt;
  final String cacheVersion;

  factory V2FamilyPhoto.parse(Object? value) {
    final raw = v2Map(value, '家庭照片');
    final contentType =
        v2Text(raw['content_type'], label: '家庭照片', max: 100);
    if (!contentType.startsWith('image/')) return v2Invalid('家庭照片');
    final cacheVersion =
        v2Text(raw['cache_version'], label: '家庭照片', max: 64);
    if (!RegExp(r'^[0-9a-f]{64}).hasMatch(cacheVersion)) {
      return v2Invalid('家庭照片');
    }
    return V2FamilyPhoto(
      mediaId: v2Uuid(raw['media_id'], '家庭照片'),
      contentType: contentType,
      sizeBytes: v2Int(raw['size_bytes'], label: '家庭照片', min: 1),
      createdAt: v2Aware(raw['created_at'], '家庭照片'),
      completedAt: v2Aware(raw['completed_at'], '家庭照片'),
      cacheVersion: cacheVersion,
    );
  }
}

List<V2FamilyMemory> parseFamilyMemories(Object? value) {
  final rows = v2List(value, '家庭记忆', 50)
      .map(V2FamilyMemory.parse)
      .toList(growable: false);
  final ids = <String>{};
  for (final row in rows) {
    if (!ids.add(row.memoryId.toLowerCase())) return v2Invalid('家庭记忆');
  }
  return List.unmodifiable(rows);
}

List<V2FamilyPhoto> parseFamilyPhotos(Object? value) {
  final rows = v2List(value, '家庭照片', 50)
      .map(V2FamilyPhoto.parse)
      .toList(growable: false);
  final ids = <String>{};
  for (final row in rows) {
    if (!ids.add(row.mediaId.toLowerCase())) return v2Invalid('家庭照片');
  }
  return List.unmodifiable(rows);
}

class V2FamilyPhotoDownload {
  const V2FamilyPhotoDownload({
    required this.mediaId,
    required this.download,
  });

  final String mediaId;
  final SignedDownloadTarget download;

  factory V2FamilyPhotoDownload.parse(
    Object? value, {
    required String expectedMediaId,
  }) {
    final raw = v2Map(value, '家庭照片下载');
    final mediaId = v2Uuid(raw['media_id'], '家庭照片下载');
    if (mediaId.toLowerCase() != expectedMediaId.toLowerCase()) {
      return v2Invalid('家庭照片下载');
    }
    final download = raw['download'];
    if (download is! Map<String, dynamic>) return v2Invalid('家庭照片下载');
    return V2FamilyPhotoDownload(
      mediaId: mediaId,
      download: SignedDownloadTarget.fromJson(download),
    );
  }
}

String familyMediaCacheKey(String resourceOwnerUserId, String mediaId) {
  final owner = v2Uuid(resourceOwnerUserId, '家庭照片').toLowerCase();
  final media = v2Uuid(mediaId, '家庭照片').toLowerCase();
  return '${owner}_$media';
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

String familyRoleLabel(String role) => role == 'OWNER' ? '家庭创建者' : '家庭成员';

String familyPermissionLabel(String code) => switch (code) {
      familyViewMemory => '可查看我的记忆',
      familyViewPhotos => '可查看我的照片',
      familyViewFootprint => '可查看我的今日足迹',
      familyViewCurrentLocation => '可查看我的当前位置',
      _ => '其他授权',
    };
).hasMatch(cacheVersion)) {
      return v2Invalid('家庭照片');
    }
    return V2FamilyPhoto(
      mediaId: v2Uuid(raw['media_id'], '家庭照片'),
      contentType: contentType,
      sizeBytes: v2Int(raw['size_bytes'], label: '家庭照片', min: 1),
      createdAt: v2Aware(raw['created_at'], '家庭照片'),
      completedAt: v2Aware(raw['completed_at'], '家庭照片'),
      cacheVersion: cacheVersion,
    );
  }
}

List<V2FamilyMemory> parseFamilyMemories(Object? value) {
  final rows = v2List(value, '家庭记忆', 50)
      .map(V2FamilyMemory.parse)
      .toList(growable: false);
  final ids = <String>{};
  for (final row in rows) {
    if (!ids.add(row.memoryId.toLowerCase())) return v2Invalid('家庭记忆');
  }
  return List.unmodifiable(rows);
}

List<V2FamilyPhoto> parseFamilyPhotos(Object? value) {
  final rows = v2List(value, '家庭照片', 50)
      .map(V2FamilyPhoto.parse)
      .toList(growable: false);
  final ids = <String>{};
  for (final row in rows) {
    if (!ids.add(row.mediaId.toLowerCase())) return v2Invalid('家庭照片');
  }
  return List.unmodifiable(rows);
}

class V2FamilyPhotoDownload {
  const V2FamilyPhotoDownload({
    required this.mediaId,
    required this.download,
  });

  final String mediaId;
  final SignedDownloadTarget download;

  factory V2FamilyPhotoDownload.parse(
    Object? value, {
    required String expectedMediaId,
  }) {
    final raw = v2Map(value, '家庭照片下载');
    final mediaId = v2Uuid(raw['media_id'], '家庭照片下载');
    if (mediaId.toLowerCase() != expectedMediaId.toLowerCase()) {
      return v2Invalid('家庭照片下载');
    }
    final download = raw['download'];
    if (download is! Map<String, dynamic>) return v2Invalid('家庭照片下载');
    return V2FamilyPhotoDownload(
      mediaId: mediaId,
      download: SignedDownloadTarget.fromJson(download),
    );
  }
}

String familyMediaCacheKey(String resourceOwnerUserId, String mediaId) {
  final owner = v2Uuid(resourceOwnerUserId, '家庭照片').toLowerCase();
  final media = v2Uuid(mediaId, '家庭照片').toLowerCase();
  return '${owner}_$media';
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

String familyRoleLabel(String role) => role == 'OWNER' ? '家庭创建者' : '家庭成员';

String familyPermissionLabel(String code) => switch (code) {
      familyViewMemory => '可查看我的记忆',
      familyViewPhotos => '可查看我的照片',
      familyViewFootprint => '可查看我的今日足迹',
      familyViewCurrentLocation => '可查看我的当前位置',
      _ => '其他授权',
    };
