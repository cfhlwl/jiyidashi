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

typedef V2OperationToken = int;

class V2OperationFlight {
  int _generation = 0;
  V2OperationToken? _active;

  V2OperationToken? begin() {
    if (_active != null) return null;
    _generation += 1;
    _active = _generation;
    return _active;
  }

  void invalidate() {
    _generation += 1;
    _active = null;
  }

  bool isCurrent(V2OperationToken token) => _active == token;

  bool end(V2OperationToken token) {
    if (_active != token) return false;
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
