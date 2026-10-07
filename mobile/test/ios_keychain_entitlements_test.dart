import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  const entitlementPaths = <String>[
    'ios/Runner/DebugProfile.entitlements',
    'ios/Runner/Release.entitlements',
  ];

  for (final path in entitlementPaths) {
    test('$path uses the app default Keychain access group', () {
      final xml = File(path).readAsStringSync();
      final compact = xml.replaceAll(RegExp(r'\s+'), ' ');

      expect(xml, contains('<key>keychain-access-groups</key>'));
      expect(
        compact,
        contains('<key>keychain-access-groups</key> <array/>'),
      );
      expect(xml, isNot(contains(r'$(AppIdentifierPrefix)')));
      expect(xml, isNot(contains('<string>com.jiyidays</string>')));
    });
  }
}
