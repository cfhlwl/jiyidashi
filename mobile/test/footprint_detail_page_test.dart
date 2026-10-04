import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/footprint_detail_page.dart';
import 'package:jiyidashi/footprint_models.dart';

class _FootprintApi extends JiYiApiClient {
  _FootprintApi() : super(baseUrl: 'https://footprint.invalid/v1') {
    accessToken = 'token';
    authenticatedUserId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  }
}

FootprintDay _day() => FootprintDay.fromJson(<String, dynamic>{
      'timezone': 'Asia/Shanghai',
      'day': '2026-10-04',
      'visits': <Map<String, dynamic>>[
        <String, dynamic>{
          'id': '11111111-1111-4111-8111-111111111111',
          'place_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          'place_name': '家',
          'place_latitude': 39.9042,
          'place_longitude': 116.4074,
          'place_address': '测试地址 1',
          'place_category': 'HOME',
          'arrived_at': '2026-10-04T00:00:00Z',
          'left_at': '2026-10-04T01:35:00Z',
          'arrived_at_local': '2026-10-04T08:00:00+08:00',
          'left_at_local': '2026-10-04T09:35:00+08:00',
          'confidence': 0.99,
          'visit_source': 'LOCATION_CLUSTER',
          'visit_finalized': true,
        },
        <String, dynamic>{
          'id': '22222222-2222-4222-8222-222222222222',
          'place_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          'place_name': '公司',
          'place_latitude': 39.9142,
          'place_longitude': 116.4174,
          'place_address': '测试地址 2',
          'place_category': 'OFFICE',
          'arrived_at': '2026-10-04T02:00:00Z',
          'left_at': null,
          'arrived_at_local': '2026-10-04T10:00:00+08:00',
          'left_at_local': null,
          'confidence': 0.97,
          'visit_source': 'LOCATION_CLUSTER',
          'visit_finalized': false,
        },
      ],
    });

void main() {
  testWidgets('footprint detail keeps factual timeline when map privacy is off',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: FootprintDetailPage(
          api: _FootprintApi(),
          footprint: _day(),
          mapPrivacyAccepted: false,
        ),
      ),
    );
    await tester.pump();

    expect(find.byKey(const ValueKey('amap-privacy-blocked')), findsOneWidget);
    expect(find.text('家'), findsWidgets);
    expect(find.text('08:00 - 09:35'), findsWidgets);
    expect(find.text('停留 1小时35分钟'), findsWidgets);
    expect(find.text('公司'), findsWidgets);
    expect(find.text('10:00 起'), findsWidgets);
  });

  testWidgets('multi-visit map copy never claims connector is exact route',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: FootprintDetailPage(
          api: _FootprintApi(),
          footprint: _day(),
          mapPrivacyAccepted: false,
        ),
      ),
    );
    await tester.pump();

    expect(find.text('地点间连线表示到访顺序'), findsOneWidget);
    expect(find.textContaining('不代表你实际步行、驾车或乘车的精确路线'), findsOneWidget);
    expect(find.textContaining('精确行驶路线'), findsNothing);
  });
}
