import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/amap_privacy_consent.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/memory_detail_page.dart';

const _owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const _memory = '11111111-1111-4111-8111-111111111111';
const _place = '22222222-2222-4222-8222-222222222222';

class _Consent implements AmapPrivacyConsentAuthority {
  _Consent(this.accepted);

  bool accepted;

  @override
  Future<void> accept() async => accepted = true;

  @override
  Future<bool> readAccepted() async => accepted;

  @override
  Future<void> revoke() async => accepted = false;
}

class _MemoryMapApi extends JiYiApiClient {
  _MemoryMapApi() : super(baseUrl: 'https://memory-map.invalid/v1') {
    accessToken = 'token';
    authenticatedUserId = _owner;
  }

  @override
  Future<Map<String, dynamic>> getMemory(String memoryId) async {
    return <String, dynamic>{
      'id': _memory,
      'user_id': _owner,
      'memory_type': 'NOTE',
      'title': '在公园散步',
      'content': '下午去了公园。',
      'occurred_at': '2026-10-04T06:00:00Z',
      'source_type': 'USER_TEXT',
      'confidence': 1.0,
      'place_id': _place,
      'latitude': null,
      'longitude': null,
      'is_confirmed': true,
      'metadata_json': const <String, dynamic>{},
      'edit_revision': 0,
      'edited_at': null,
      'created_at': '2026-10-04T06:00:00Z',
    };
  }

  @override
  Future<Map<String, dynamic>> getPlaceDetail(
    String placeId, {
    int limit = 20,
    String? cursor,
  }) async {
    return <String, dynamic>{
      'place': <String, dynamic>{
        'id': _place,
        'name': '测试公园',
        'name_source': 'AMAP_REVERSE_GEOCODE',
        'latitude': 39.9042,
        'longitude': 116.4074,
        'address': '测试路 1 号',
        'category': 'PARK',
        'visit_count': 1,
        'first_arrived_at': '2026-10-04T06:00:00Z',
        'last_arrived_at': '2026-10-04T06:00:00Z',
      },
      'visits': const <dynamic>[],
      'next_cursor': null,
    };
  }
}

void main() {
  testWidgets('Memory Detail keeps canonical place facts when map privacy is off',
      (tester) async {
    final consent = _Consent(false);
    await tester.pumpWidget(
      MaterialApp(
        home: MemoryDetailPage(
          api: _MemoryMapApi(),
          memoryId: _memory,
          amapPrivacyConsent: consent,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('测试公园'), findsWidgets);
    expect(find.byKey(const ValueKey('amap-place-privacy-blocked')), findsOneWidget);
    expect(find.byKey(const ValueKey('memory-amap-privacy-accept')), findsOneWidget);
  });

  testWidgets('Memory Detail privacy accept leaves factual map fallback usable',
      (tester) async {
    final consent = _Consent(false);
    await tester.pumpWidget(
      MaterialApp(
        home: MemoryDetailPage(
          api: _MemoryMapApi(),
          memoryId: _memory,
          amapPrivacyConsent: consent,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('memory-amap-privacy-accept')));
    await tester.pumpAndSettle();

    expect(find.textContaining('高德地图 SDK'), findsOneWidget);
    expect(consent.accepted, isFalse);

    await tester.tap(find.byKey(const ValueKey('amap-privacy-confirm')));
    await tester.pumpAndSettle();

    expect(consent.accepted, isTrue);
    expect(find.byKey(const ValueKey('amap-place-privacy-blocked')), findsNothing);
    expect(find.text('测试公园'), findsWidgets);
  });
}
