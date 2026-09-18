import 'dart:async';

import 'api_client.dart';
import 'offline_queue.dart';

class OfflineFlushReport {
  const OfflineFlushReport({
    required this.attempted,
    required this.completed,
    required this.retryableFailures,
    required this.blockedFailures,
  });

  final int attempted;
  final int completed;
  final int retryableFailures;
  final int blockedFailures;
}

class OfflineSyncCoordinator {
  OfflineSyncCoordinator({
    required JiYiApiClient api,
    required OfflineQueueStore store,
  })  : _api = api,
        _store = store;

  static const String objectLocationOperation = OfflineQueueStore.objectLocationOperation;

  final JiYiApiClient _api;
  final OfflineQueueStore _store;
  Future<OfflineFlushReport>? _activeFlush;
  String? _activeOwner;

  // 同一 coordinator 同一时刻只允许一个 flush；UI 连点和生命周期重复 resumed
  // 都复用同一个 Future，避免并发发送同一 SQLite outbox。
  Future<OfflineFlushReport> flush(String ownerUserId) {
    final owner = ownerUserId.trim();
    if (owner.isEmpty) {
      throw ArgumentError.value(ownerUserId, 'ownerUserId', 'owner user ID is required');
    }
    final active = _activeFlush;
    if (active != null) {
      if (_activeOwner == owner) return active;
      return active.then((_) => flush(owner), onError: (_) => flush(owner));
    }

    late final Future<OfflineFlushReport> tracked;
    tracked = _flushOnce(owner).whenComplete(() {
      if (identical(_activeFlush, tracked)) {
        _activeFlush = null;
        _activeOwner = null;
      }
    });
    _activeOwner = owner;
    _activeFlush = tracked;
    return tracked;
  }

  Future<OfflineFlushReport> _flushOnce(String owner) async {
    if (_api.authenticatedUserId != owner) {
      throw StateError('Offline sync owner does not match authenticated user');
    }
    final sessionVersion = _api.sessionVersion;
    final deliverable = await _store.listDeliverable(owner);
    var attempted = 0;
    var completed = 0;
    var retryableFailures = 0;
    var blockedFailures = 0;

    for (final initial in deliverable) {
      // 账号在 flush 中途退出或切换时停止后续任务；已经开始的逻辑 mutation
      // 自己负责使用固定认证快照，完成结果也只写回原 owner 行。
      if (_api.authenticatedUserId != owner ||
          _api.sessionVersion != sessionVersion) {
        break;
      }

      var item = initial;
      if (item.status == OfflineQueueStatus.failed) {
        item = await _store.retryFailed(owner, item.clientUuid);
      }
      if (item.status != OfflineQueueStatus.pending) continue;

      try {
        item = await _store.markSending(owner, item.clientUuid);
      } on StateError {
        // deliverable snapshot 之后用户仍可能取消任务；若当前行已经进入终态就跳过，
        // 不能为了继续 flush 把 cancelled 恢复 pending。
        final current = await _store.findByClientUuid(owner, item.clientUuid);
        if (current == null || current.isTerminal) continue;
        rethrow;
      }
      attempted += 1;
      try {
        final resourceId = await _sendItem(item);
        await _store.markCompleted(
          owner,
          item.clientUuid,
          serverResourceId: resourceId,
        );
        completed += 1;
      } on TransportException catch (exc) {
        await _store.markFailed(
          owner,
          item.clientUuid,
          exc.message,
          retryable: true,
        );
        retryableFailures += 1;
      } on ApiException catch (exc) {
        final retryable = _isRetryableHttpStatus(exc.statusCode);
        await _store.markFailed(
          owner,
          item.clientUuid,
          'HTTP ${exc.statusCode}: ${exc.message}',
          retryable: retryable,
        );
        if (retryable) {
          retryableFailures += 1;
        } else {
          blockedFailures += 1;
        }
        if (_shouldStopFlushAfterHttpFailure(exc.statusCode)) {
          break;
        }
      } on ProtocolException catch (exc) {
        await _store.markFailed(
          owner,
          item.clientUuid,
          exc.message,
          retryable: false,
        );
        blockedFailures += 1;
      } catch (_) {
        await _store.markFailed(
          owner,
          item.clientUuid,
          '客户端同步处理异常',
          retryable: false,
        );
        blockedFailures += 1;
      }
    }

    return OfflineFlushReport(
      attempted: attempted,
      completed: completed,
      retryableFailures: retryableFailures,
      blockedFailures: blockedFailures,
    );
  }

  // 每种 outbox operation 都只能把同一个 client_uuid 发送到对应服务端幂等入口；
  // 本地 payload 结构异常直接阻断，不能猜字段或换 key 重试。
  Future<String> _sendItem(OfflineQueueItem item) async {
    switch (item.operationType) {
      case OfflineQueueStore.textMemoryOperation:
        final content = item.payload['content'];
        final title = item.payload['title'];
        if (content is! String || content.trim().isEmpty) {
          throw ProtocolException('本地离线任务格式不正确');
        }
        if (title != null && title is! String) {
          throw ProtocolException('本地离线任务格式不正确');
        }
        final occurredAt = _stablePayloadTime(item, 'occurred_at');
        final response = await _api.createTextMemory(
          title: title as String?,
          content: content,
          occurredAt: occurredAt,
          clientUuid: item.clientUuid,
        );
        return _resourceId(response, 'Memory');
      case objectLocationOperation:
        final objectName = item.payload['object_name'];
        final locationText = item.payload['location_text'];
        if (objectName is! String ||
            objectName.trim().isEmpty ||
            locationText is! String ||
            locationText.trim().isEmpty) {
          throw ProtocolException('本地离线任务格式不正确');
        }
        final recordedAt = _stablePayloadTime(item, 'recorded_at');
        final response = await _api.rememberObjectLocation(
          objectName: objectName,
          locationText: locationText,
          recordedAt: recordedAt,
          clientUuid: item.clientUuid,
        );
        return _resourceId(response, 'ObjectLocation');
      default:
        throw ProtocolException('不支持的离线操作类型：${item.operationType}');
    }
  }

  DateTime _stablePayloadTime(OfflineQueueItem item, String field) {
    final raw = item.payload[field];
    if (raw == null) {
      // 兼容升级前已经落盘的任务：createdAt 是首次入队时刻，
      // 比“现在同步”更接近真实发生时间，并且在所有重试中保持稳定。
      return item.createdAt.toUtc();
    }
    if (raw is! String) {
      throw ProtocolException('本地离线任务格式不正确');
    }
    final parsed = DateTime.tryParse(raw);
    if (parsed == null || !parsed.isUtc) {
      throw ProtocolException('本地离线任务时间格式不正确');
    }
    return parsed;
  }

  bool _isRetryableHttpStatus(int statusCode) {
    return statusCode == 401 ||
        statusCode == 403 ||
        statusCode == 408 ||
        statusCode == 429 ||
        (statusCode >= 500 && statusCode <= 599);
  }

  bool _shouldStopFlushAfterHttpFailure(int statusCode) {
    return statusCode == 401 || statusCode == 403 || statusCode == 429;
  }

  String _resourceId(Map<String, dynamic> response, String resourceName) {
    final resourceId = response['id'];
    if (resourceId is! String || resourceId.trim().isEmpty) {
      throw ProtocolException('服务端成功响应缺少 $resourceName ID');
    }
    return resourceId;
  }
}
