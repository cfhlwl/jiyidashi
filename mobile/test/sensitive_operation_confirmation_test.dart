import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/sensitive_operation_confirmation.dart';

void main() {
  test('SEC-014 specs use explicit product-safe action language', () {
    const exportSpec = SensitiveOperationSpec.dataExport();
    const deleteSpec = SensitiveOperationSpec.dataDelete();
    const accountSpec = SensitiveOperationSpec.accountDelete();
    const locationSpec = SensitiveOperationSpec.automaticLocationStart();

    expect(exportSpec.confirmLabel, '导出这些数据');
    expect(deleteSpec.confirmLabel, '删除这些数据');
    expect(accountSpec.requiredPhrase, '注销账号');
    expect(accountSpec.confirmLabel, '永久注销');
    expect(locationSpec.confirmLabel, '开始位置记忆');

    final grant = SensitiveOperationSpec.familyPermission(
      enabled: true,
      permissionLabel: '我允许 TA 查看我的照片',
      memberLabel: '该家庭成员',
    );
    final revoke = SensitiveOperationSpec.familyPermission(
      enabled: false,
      permissionLabel: '我允许 TA 查看我的照片',
      memberLabel: '该家庭成员',
    );
    expect(grant.confirmLabel, '允许查看');
    expect(revoke.confirmLabel, '取消授权');

    for (final text in [
      exportSpec.title,
      deleteSpec.title,
      accountSpec.title,
      grant.title,
      revoke.title,
      locationSpec.title,
    ]) {
      expect(text, isNot(contains('OWNER')));
      expect(text, isNot(contains('VIEW_')));
      expect(text, isNot(contains('DELETE_MY_')));
    }
  });

  test('SEC-014 error mapping never publishes raw backend enum text', () {
    expect(
      sensitiveOperationSafeError(ApiException(403, 'FAMILY_OWNER_REQUIRED')),
      '你现在没有权限执行这个操作',
    );
    expect(
      sensitiveOperationSafeError(
        ApiException(409, 'DATA_DELETION_REQUEST_STALE'),
      ),
      '状态刚刚发生变化，请重新打开后再试',
    );
    expect(
      sensitiveOperationSafeError(ApiException(500, 'INTERNAL_SECRET_CODE')),
      '操作暂时没有完成，请稍后重试',
    );
  });

  testWidgets('cancel returns false without authorizing an operation', (tester) async {
    bool? result;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => FilledButton(
            onPressed: () async {
              result = await showSensitiveOperationConfirmation(
                context,
                SensitiveOperationSpec.familyPermission(
                  enabled: true,
                  permissionLabel: '我允许 TA 查看我的照片',
                  memberLabel: '该家庭成员',
                ),
              );
            },
            child: const Text('打开'),
          ),
        ),
      ),
    );

    await tester.tap(find.text('打开'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('family-grant-confirm-cancel')));
    await tester.pumpAndSettle();
    expect(result, isFalse);
  });

  testWidgets('account delete retains typed irreversible confirmation', (tester) async {
    bool? result;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => FilledButton(
            onPressed: () async {
              result = await showSensitiveOperationConfirmation(
                context,
                const SensitiveOperationSpec.accountDelete(),
              );
            },
            child: const Text('打开注销'),
          ),
        ),
      ),
    );

    await tester.tap(find.text('打开注销'));
    await tester.pumpAndSettle();
    final submit = find.byKey(const ValueKey('account-delete-confirm-submit'));
    expect(tester.widget<FilledButton>(submit).onPressed, isNull);
    await tester.enterText(
      find.byKey(const ValueKey('account-delete-confirm-input')),
      '注销账号',
    );
    await tester.pump();
    expect(tester.widget<FilledButton>(submit).onPressed, isNotNull);
    await tester.tap(submit);
    await tester.pumpAndSettle();
    expect(result, isTrue);
  });
}
