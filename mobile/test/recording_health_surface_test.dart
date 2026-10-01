import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/auth_session_store.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/recording_health_section.dart';

const _headers = <String, String>{
  'content-type': 'application/json; charset=utf-8',
};

http.Response _loginResponse({
  required String userId,
  required String sessionId,
  required String suffix,
}) {
  return http.Response(
    jsonEncode(<String, dynamic>{
      'access_token': 'access-$suffix',
      'refresh_token': 'refresh-token-$suffix-1234567890',
      'session_id': sessionId,
      'token_type': 'bearer',
      'user_id': userId,
      'access_expires_at': '2030-10-01T00:00:00Z',
    }),
    200,
    headers: _headers,
  );
}

Map<String, dynamic> _healthResponse({
  String status = 'UNKNOWN',
  String reason = 'NATIVE_STATE_UNAVAILABLE',
}) {
  return <String, dynamic>{
    'health': <String, dynamic>{
      'status': status,
      'status_reason': reason,
      'automatic_enabled': status == 'HEALTHY',
      'privacy_paused': status == 'PAUSED',
      'permission_state': status == 'BLOCKED' ? 'DENIED' : null,
      'location_services_state': 'ON',
      'background_runtime_state': 'ELIGIBLE',
      'battery_optimization_state': 'OPTIMIZED',
      'native_producer_state': status == 'HEALTHY' ? 'RUNNING' : 'STOPPED',
      'native_queue_depth': 0,
      'native_queue_capacity': 1000,
      'native_oldest_pending_at': null,
      'sqlite_queue_depth': 0,
      'capacity_pressure': false,
      'last_fix_at': status == 'HEALTHY' ? '2026-10-01T10:00:00Z' : null,
      'last_enqueue_at': null,
      'last_handoff_at': null,
      'last_upload_attempt_at': null,
      'last_upload_success_at': null,
      'last_server_ack_at':
          status == 'HEALTHY' ? '2026-10-01T10:01:00Z' : null,
      'last_visit_at': null,
      'delivery_failure_count': 0,
      'last_delivery_error_code': null,
      'recovery_pending': status == 'RECOVERING',
      'recording_gap_state': status == 'HEALTHY' ? 'NONE' : 'UNKNOWN',
      'updated_at': '2026-10-01T10:02:00Z',
    },
    'today': <String, dynamic>{
      'local_day': '2026-10-01',
      'timezone': 'Asia/Shanghai',
      'first_observed_at': null,
      'last_observed_at': null,
      'trusted_location_sample_count': 0,
      'visit_count': 0,
      'memory_count': 0,
      'covered_duration_seconds': 0,
      'known_gap_duration_seconds': 0,
      'largest_known_gap_seconds': 0,
      'coverage_state': 'UNKNOWN',
      'has_capacity_pressure': false,
      'has_recorded_gap': false,
      'recent_gaps': <Object?>[],
    },
    'aggregates': <String, dynamic>{
      'healthy_days_7d': 0,
      'healthy_days_30d': 0,
      'gap_hours_7d': 0,
      'gap_hours_30d': 0,
      'days_with_capacity_pressure': null,
      'days_with_permission_block': null,
      'current_capacity_pressure': null,
      'current_permission_block': null,
    },
    'recent_gaps': <Object?>[],
    'server_observed_at': '2026-10-01T10:02:00Z',
    'native_state_observed': status != 'UNKNOWN',
  };
}

void main() {
  test('late owner-A health response is discarded after account switch', () async {
    final delayedHealth = Completer<http.Response>();
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: MemoryAuthSessionStore(),
      httpClient: MockClient((request) async {
        if (request.url.path == '/v1/auth/login') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          if (body['email'] == 'a@example.test') {
            return _loginResponse(
              userId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
              sessionId: '11111111-1111-4111-8111-111111111111',
              suffix: 'a',
            );
          }
          return _loginResponse(
            userId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            sessionId: '22222222-2222-4222-8222-222222222222',
            suffix: 'b',
          );
        }
        if (request.url.path == '/v1/recording/health') {
          expect(request.method, 'GET');
          expect(request.headers['authorization'], 'Bearer access-a');
          return delayedHealth.future;
        }
        fail('Unexpected request ${request.method} ${request.url}');
      }),
    );

    await api.login(email: 'a@example.test', password: 'password-a');
    final pending = api.getRecordingHealth();
    await Future<void>.delayed(Duration.zero);
    await api.login(email: 'b@example.test', password: 'password-b');
    delayedHealth.complete(
      http.Response(
        jsonEncode(_healthResponse(status: 'HEALTHY', reason: 'RECENT_CAPTURE_AND_ACK')),
        200,
        headers: _headers,
      ),
    );

    await expectLater(pending, throwsA(isA<ProtocolException>()));
    expect(api.authenticatedUserId, 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');
  });

  test('recording health POST keeps exact authenticated session', () async {
    var healthCalls = 0;
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: MemoryAuthSessionStore(),
      httpClient: MockClient((request) async {
        if (request.url.path == '/v1/auth/login') {
          return _loginResponse(
            userId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            sessionId: '11111111-1111-4111-8111-111111111111',
            suffix: 'a',
          );
        }
        healthCalls += 1;
        expect(request.url.path, '/v1/recording/health');
        expect(request.method, 'POST');
        expect(request.headers['authorization'], 'Bearer access-a');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['platform'], 'android');
        expect(body.containsKey('user_id'), isFalse);
        return http.Response(
          jsonEncode(_healthResponse(status: 'DEGRADED', reason: 'QUEUE_BACKLOG')),
          200,
          headers: _headers,
        );
      }),
    );

    await api.login(email: 'a@example.test', password: 'password-a');
    final result = await api.getRecordingHealth(
      clientState: <String, dynamic>{'platform': 'android'},
    );
    expect(result['health']['status'], 'DEGRADED');
    expect(healthCalls, 1);
  });

  testWidgets('health surface never renders developer enum as user copy', (tester) async {
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: MemoryAuthSessionStore(),
      httpClient: MockClient((request) async {
        if (request.url.path == '/v1/auth/login') {
          return _loginResponse(
            userId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            sessionId: '11111111-1111-4111-8111-111111111111',
            suffix: 'a',
          );
        }
        expect(request.url.path, '/v1/recording/health');
        return http.Response(
          jsonEncode(
            _healthResponse(status: 'BLOCKED', reason: 'PERMISSION_BLOCKED'),
          ),
          200,
          headers: _headers,
        );
      }),
    );
    await api.login(email: 'a@example.test', password: 'password-a');

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: RecordingHealthSection(
            api: api,
            store: OfflineQueueStore(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('自动记录当前受阻'), findsOneWidget);
    expect(find.textContaining('系统定位权限不足'), findsOneWidget);
    expect(find.text('PERMISSION_BLOCKED'), findsNothing);
    expect(find.text('今天记录状态正常'), findsNothing);
  });

  testWidgets('unknown server-observed health is visibly fail-closed', (tester) async {
    final api = JiYiApiClient(
      baseUrl: 'https://example.test/v1',
      sessionStore: MemoryAuthSessionStore(),
      httpClient: MockClient((request) async {
        if (request.url.path == '/v1/auth/login') {
          return _loginResponse(
            userId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            sessionId: '11111111-1111-4111-8111-111111111111',
            suffix: 'a',
          );
        }
        return http.Response(
          jsonEncode(_healthResponse()),
          200,
          headers: _headers,
        );
      }),
    );
    await api.login(email: 'a@example.test', password: 'password-a');

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: RecordingHealthSection(
            api: api,
            store: OfflineQueueStore(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('当前记录状态未知'), findsOneWidget);
    expect(find.textContaining('无法从这里确认这台手机当前的后台状态'), findsOneWidget);
    expect(find.text('今天记录状态正常'), findsNothing);
  });
}
