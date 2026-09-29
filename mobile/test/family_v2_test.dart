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
