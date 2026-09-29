import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/v2/v2_authority.dart';

const ownerA = '11111111-1111-4111-8111-111111111111';
const ownerB = '22222222-2222-4222-8222-222222222222';

JiYiApiClient signedIn(String owner, String token) {
  final api = JiYiApiClient(baseUrl: 'https://example.test/v1');
  api.authenticatedUserId = owner;
  api.accessToken = token;
  return api;
}

void main() {
  test('V2 authority binds owner, session and resource identity', () {
    final api = signedIn(ownerA, 'token-a');
    final authority = V2Authority();
    final first = authority.capture(api, 'people:list');
    expect(authority.isCurrent(api, first, 'people:list'), isTrue);

    final second = authority.capture(api, 'person:' + ownerB);
    expect(authority.isCurrent(api, first, 'people:list'), isFalse);
    expect(authority.isCurrent(api, second, 'person:' + ownerB), isTrue);

    api.logout();
    expect(authority.isCurrent(api, second, 'person:' + ownerB), isFalse);
  });

  test('session switch releases old operation token and stale finally cannot clear B', () {
    final api = signedIn(ownerA, 'token-a');
    final flight = V2OperationFlight();
    final tokenA = flight.begin(api);
    expect(tokenA, isNotNull);

    api.logout();
    api.authenticatedUserId = ownerB;
    api.accessToken = 'token-b';

    final tokenB = flight.begin(api);
    expect(tokenB, isNotNull);
    expect(flight.isCurrent(tokenB!, api), isTrue);
    expect(flight.end(tokenA!), isFalse);
    expect(flight.isCurrent(tokenB, api), isTrue);
    expect(flight.end(tokenB), isTrue);
  });

  test('stale success/error stops chained continuation after account switch', () async {
    for (final settleError in [false, true]) {
      final api = signedIn(ownerA, 'token-a');
      final authority = V2Authority();
      final flight = V2OperationFlight();
      final operation = beginV2Operation(
        api,
        authority,
        flight,
        'person:update:' + ownerA,
      );
      expect(operation, isNotNull);

      final completer = Completer<void>();
      var firstStarted = false;
      var secondRequested = false;
      final continuation = continueV2Operation(
        api,
        authority,
        operation!.snapshot,
        [
          () async {
            firstStarted = true;
            await completer.future;
          },
          () async {
            secondRequested = true;
          },
        ],
      );

      await Future<void>.delayed(Duration.zero);
      expect(firstStarted, isTrue);

      api.logout();
      api.authenticatedUserId = ownerB;
      api.accessToken = 'token-b';

      final tokenB = flight.begin(api);
      expect(tokenB, isNotNull);

      if (settleError) {
        completer.completeError(StateError('old owner refresh failed'));
      } else {
        completer.complete();
      }

      expect(await continuation, isFalse);
      expect(secondRequested, isFalse);
      expect(flight.end(operation.token), isFalse);
      expect(flight.isCurrent(tokenB!, api), isTrue);
      expect(flight.end(tokenB), isTrue);
    }
  });

  test('same owner/session exact operation is single-flight', () {
    final api = signedIn(ownerA, 'token-a');
    final authority = V2Authority();
    final flight = V2OperationFlight();

    final first = beginV2Operation(
      api,
      authority,
      flight,
      'life-stage:reason:stage-a',
    );
    expect(first, isNotNull);

    final duplicate = beginV2Operation(
      api,
      authority,
      flight,
      'life-stage:reason:stage-a',
    );
    expect(duplicate, isNull);
    expect(flight.isCurrent(first!.token, api), isTrue);

    expect(flight.end(first.token), isTrue);
    final afterFinish = beginV2Operation(
      api,
      authority,
      flight,
      'life-stage:reason:stage-a',
    );
    expect(afterFinish, isNotNull);
  });

  test('resource range and year generation invalidate stale success and error', () async {
    final api = signedIn(ownerA, 'token-a');
    final authority = V2Authority();

    for (final identities in [
      ['person:' + ownerA, 'person:' + ownerB],
      ['history:2020:2024:root', 'history:2021:2025:root'],
      ['annual:2024', 'annual:2025'],
      ['chapter:stage-a', 'chapter:stage-b'],
    ]) {
      final old = authority.capture(api, identities[0]);
      expect(authority.isCurrent(api, old, identities[0]), isTrue);

      final current = authority.capture(api, identities[1]);
      expect(authority.isCurrent(api, old, identities[0]), isFalse);
      expect(authority.isCurrent(api, current, identities[1]), isTrue);

      var publishedSuccess = false;
      var publishedError = false;
      if (authority.isCurrent(api, old, identities[0])) {
        publishedSuccess = true;
      }
      if (authority.isCurrent(api, old, identities[0])) {
        publishedError = true;
      }
      expect(publishedSuccess, isFalse);
      expect(publishedError, isFalse);
    }

    final disposed = authority.capture(api, 'graph:PERSON:' + ownerA);
    authority.invalidate();
    expect(
      authority.isCurrent(api, disposed, 'graph:PERSON:' + ownerA),
      isFalse,
    );
  });

}
