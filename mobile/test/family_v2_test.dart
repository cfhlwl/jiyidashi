import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/v2/family_models.dart';

void main() {
  const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  const member = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

  test('Family parser binds current authenticated member and exact role', () {
    final family = V2Family.parse({
      'family_id': 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      'current_user_role': 'OWNER',
      'members': [
        {
          'user_id': owner,
          'role': 'OWNER',
          'created_at': '2026-09-29T00:00:00Z',
        },
        {
          'user_id': member,
          'role': 'MEMBER',
          'created_at': '2026-09-29T00:00:00Z',
        },
      ],
    }, currentUserId: owner);

    expect(family.currentUserRole, 'OWNER');
    expect(family.members.length, 2);
  });

  test('Family parser fails closed for duplicate members and role mismatch', () {
    expect(
      () => V2Family.parse({
        'family_id': 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        'current_user_role': 'MEMBER',
        'members': [
          {
            'user_id': owner,
            'role': 'OWNER',
            'created_at': '2026-09-29T00:00:00Z',
          },
        ],
      }, currentUserId: owner),
      throwsA(anything),
    );

    expect(
      () => V2Family.parse({
        'family_id': 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        'current_user_role': 'OWNER',
        'members': [
          {
            'user_id': owner,
            'role': 'OWNER',
            'created_at': '2026-09-29T00:00:00Z',
          },
          {
            'user_id': owner,
            'role': 'OWNER',
            'created_at': '2026-09-29T00:00:00Z',
          },
        ],
      }, currentUserId: owner),
      throwsA(anything),
    );
  });

  test('family shared read models bind owner and stable photo cache identity', () {
    final location = V2FamilyCurrentLocation.parse(
      {
        'resource_owner_user_id': member,
        'latitude': 31.2304,
        'longitude': 121.4737,
        'accuracy': 8.0,
        'recorded_at': '2026-10-04T10:00:00Z',
        'fresh_until': '2026-10-04T10:15:00Z',
      },
      expectedResourceOwnerUserId: member,
    );
    expect(location.latitude, 31.2304);

    final photos = parseFamilyPhotos([
      {
        'media_id': 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
        'content_type': 'image/jpeg',
        'size_bytes': 2048,
        'created_at': '2026-10-04T09:00:00Z',
        'completed_at': '2026-10-04T09:00:01Z',
        'cache_version':
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      },
    ]);
    expect(photos.single.cacheVersion.length, 64);
    expect(
      familyMediaCacheKey(member, photos.single.mediaId),
      '${member}_${photos.single.mediaId}',
    );
  });

  test('family shared read models fail closed on owner or cache identity drift', () {
    expect(
      () => V2FamilyCurrentLocation.parse(
        {
          'resource_owner_user_id': owner,
          'latitude': 31.2304,
          'longitude': 121.4737,
          'accuracy': null,
          'recorded_at': '2026-10-04T10:00:00Z',
          'fresh_until': '2026-10-04T10:15:00Z',
        },
        expectedResourceOwnerUserId: member,
      ),
      throwsA(anything),
    );

    expect(
      () => parseFamilyPhotos([
        {
          'media_id': 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
          'content_type': 'image/jpeg',
          'size_bytes': 2048,
          'created_at': '2026-10-04T09:00:00Z',
          'completed_at': '2026-10-04T09:00:01Z',
          'cache_version': 'not-a-cache-version',
        },
      ]),
      throwsA(anything),
    );
  });

  test('permission replacement preserves unknown future codes while toggling known code', () {
    final grant = V2FamilyPermissionGrant.parse({
      'grantee_user_id': member,
      'permissions': ['FUTURE_PERMISSION', familyViewMemory],
    });
    final next = grant.toggle(familyViewPhotos, true).toggle(familyViewMemory, false);

    expect(next.permissions, contains('FUTURE_PERMISSION'));
    expect(next.permissions, contains(familyViewPhotos));
    expect(next.permissions, isNot(contains(familyViewMemory)));
  });

  test('permission parser rejects duplicate grant rows and duplicate codes', () {
    expect(
      () => parseFamilyPermissions([
        {'grantee_user_id': member, 'permissions': [familyViewMemory]},
        {'grantee_user_id': member, 'permissions': [familyViewPhotos]},
      ]),
      throwsA(anything),
    );
    expect(
      () => V2FamilyPermissionGrant.parse({
        'grantee_user_id': member,
        'permissions': [familyViewMemory, familyViewMemory],
      }),
      throwsA(anything),
    );
  });
}
