import '../api_client.dart';

class V2AuthoritySnapshot {
  const V2AuthoritySnapshot({
    required this.generation,
    required this.owner,
    required this.sessionVersion,
    required this.identity,
  });

  final int generation;
  final String owner;
  final int sessionVersion;
  final String identity;
}

class V2Authority {
  int _generation = 0;

  void invalidate() {
    _generation += 1;
  }

  V2AuthoritySnapshot capture(JiYiApiClient api, String identity) {
    final owner = api.authenticatedUserId?.trim();
    if (owner == null || owner.isEmpty) {
      throw ApiException(401, '请先登录');
    }
    final normalizedIdentity = identity.trim();
    if (normalizedIdentity.isEmpty) {
      throw StateError('V2 request identity must not be empty');
    }
    _generation += 1;
    return V2AuthoritySnapshot(
      generation: _generation,
      owner: owner,
      sessionVersion: api.sessionVersion,
      identity: normalizedIdentity,
    );
  }

  bool isCurrent(
    JiYiApiClient api,
    V2AuthoritySnapshot snapshot,
    String identity,
  ) {
    return snapshot.generation == _generation &&
        snapshot.owner == api.authenticatedUserId &&
        snapshot.sessionVersion == api.sessionVersion &&
        snapshot.identity == identity;
  }
}

class V2OperationToken {
  const V2OperationToken({
    required this.generation,
    required this.owner,
    required this.sessionVersion,
  });

  final int generation;
  final String owner;
  final int sessionVersion;
}

class V2OperationContext {
  const V2OperationContext({
    required this.snapshot,
    required this.token,
  });

  final V2AuthoritySnapshot snapshot;
  final V2OperationToken token;
}

V2OperationContext? beginV2Operation(
  JiYiApiClient api,
  V2Authority authority,
  V2OperationFlight flight,
  String identity,
) {
  final token = flight.begin(api);
  if (token == null) return null;
  try {
    return V2OperationContext(
      snapshot: authority.capture(api, identity),
      token: token,
    );
  } catch (_) {
    flight.end(token);
    rethrow;
  }
}

class V2OperationFlight {
  int _generation = 0;
  V2OperationToken? _active;

  V2OperationToken? begin(JiYiApiClient api) {
    final owner = api.authenticatedUserId?.trim();
    if (owner == null || owner.isEmpty) {
      throw ApiException(401, '请先登录');
    }
    final current = _active;
    if (current != null) {
      final sameSession = current.owner == owner &&
          current.sessionVersion == api.sessionVersion;
      if (sameSession) return null;
      // Account/session changed while old work is still pending. Release only the
      // obsolete token; its stale finally cannot end the new token below.
      _generation += 1;
      _active = null;
    }
    _generation += 1;
    final token = V2OperationToken(
      generation: _generation,
      owner: owner,
      sessionVersion: api.sessionVersion,
    );
    _active = token;
    return token;
  }

  void invalidate() {
    _generation += 1;
    _active = null;
  }

  bool isCurrent(V2OperationToken token, JiYiApiClient api) {
    final active = _active;
    return identical(active, token) &&
        active?.generation == token.generation &&
        token.owner == api.authenticatedUserId &&
        token.sessionVersion == api.sessionVersion;
  }

  bool end(V2OperationToken token) {
    if (!identical(_active, token)) return false;
    _active = null;
    return true;
  }

  bool get isPending => _active != null;
}

Future<bool> continueV2Operation(
  JiYiApiClient api,
  V2Authority authority,
  V2AuthoritySnapshot snapshot,
  List<Future<void> Function()> steps,
) async {
  bool current() => authority.isCurrent(api, snapshot, snapshot.identity);

  for (final step in steps) {
    if (!current()) return false;
    try {
      await step();
    } catch (_) {
      if (!current()) return false;
      rethrow;
    }
  }
  return current();
}
