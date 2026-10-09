import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import 'amap_footprint_map.dart';
import 'amap_privacy_consent.dart';
import 'api_client.dart';
import 'media_presentation_cache.dart';
import 'reminder_page.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';
import 'ui/jiyi_v3_components.dart';

typedef LocalPhotoRenderer = Widget Function(File file, Key key);

class MemoryDetailPage extends StatefulWidget {
  const MemoryDetailPage({
    super.key,
    required this.api,
    required this.memoryId,
    this.mediaCache,
    this.localPhotoRenderer,
    this.amapPrivacyConsent,
  });

  final JiYiApiClient api;
  final String memoryId;
  final LocalMediaCache? mediaCache;
  final LocalPhotoRenderer? localPhotoRenderer;
  final AmapPrivacyConsentAuthority? amapPrivacyConsent;

  @override
  State<MemoryDetailPage> createState() => _MemoryDetailPageState();
}

class _MemoryDetailPageState extends State<MemoryDetailPage> {
  _MemoryDetailView? memory;
  String? placeName;
  String? placeAddress;
  double? placeLatitude;
  double? placeLongitude;
  late final AmapPrivacyConsentAuthority _amapPrivacyConsent;
  bool _mapPrivacyAccepted = false;
  File? photoFile;
  String? photoError;
  bool photoRefreshing = false;
  late final LocalMediaCache _mediaCache;
  bool loading = true;
  bool mutating = false;
  bool reminderBusy = false;
  String? error;
  String? status;

  @override
  void initState() {
    super.initState();
    _mediaCache = widget.mediaCache ?? LocalMediaCache();
    _amapPrivacyConsent =
        widget.amapPrivacyConsent ?? AmapPrivacyConsentStore();
    _loadMapPrivacy();
    _load();
  }

  Future<void> _loadMapPrivacy() async {
    try {
      final accepted = await _amapPrivacyConsent.readAccepted();
      if (mounted) setState(() => _mapPrivacyAccepted = accepted);
    } catch (_) {
      if (mounted) setState(() => _mapPrivacyAccepted = false);
    }
  }

  Future<void> _acceptMapPrivacy() async {
    final accepted =
        await requestAmapPrivacyConsent(context, _amapPrivacyConsent);
    if (mounted && accepted) setState(() => _mapPrivacyAccepted = true);
  }

  @override
  void didUpdateWidget(covariant MemoryDetailPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.memoryId != widget.memoryId) _load();
  }

  bool _sessionCurrent(int version, String? owner) =>
      mounted &&
      widget.api.sessionVersion == version &&
      widget.api.authenticatedUserId == owner;

  Future<void> _load() async {
    final version = widget.api.sessionVersion;
    final owner = widget.api.authenticatedUserId;
    if (owner == null || owner.trim().isEmpty) {
      setState(() {
        loading = false;
        error = '请先登录';
      });
      return;
    }
    setState(() {
      loading = true;
      error = null;
      placeName = null;
      placeAddress = null;
      placeLatitude = null;
      placeLongitude = null;
      photoFile = null;
      photoError = null;
      photoRefreshing = false;
    });
    try {
      final raw = await widget.api.getMemory(widget.memoryId);
      if (!_sessionCurrent(version, owner)) return;
      final parsed = _MemoryDetailView.parse(
        raw,
        expectedId: widget.memoryId,
        expectedOwnerId: owner,
      );

      String? resolvedPlace;
      String? resolvedAddress;
      double? resolvedLatitude;
      double? resolvedLongitude;
      File? resolvedPhoto;
      String? resolvedPhotoError;
      final placeId = parsed.placeId;
      if (placeId != null) {
        try {
          final rawPlace = await widget.api.getPlaceDetail(placeId, limit: 1);
          if (!_sessionCurrent(version, owner)) return;
          final place = rawPlace['place'];
          if (place is Map<String, dynamic> &&
              place['id']?.toString().toLowerCase() == placeId.toLowerCase()) {
            final name = place['name']?.toString().trim() ?? '';
            if (name.isNotEmpty) resolvedPlace = name;
            final address = place['address'];
            if (address is String && address.trim().isNotEmpty) {
              resolvedAddress = address.trim();
            }
            final latitude = _memoryPlaceCoordinate(
              place['latitude'],
              latitudeAxis: true,
            );
            final longitude = _memoryPlaceCoordinate(
              place['longitude'],
              latitudeAxis: false,
            );
            if ((latitude == null) == (longitude == null)) {
              resolvedLatitude = latitude;
              resolvedLongitude = longitude;
            }
          }
        } catch (_) {
          if (!_sessionCurrent(version, owner)) return;
        }
      }

      final mediaId = parsed.mediaId;
      if (parsed.memoryType == 'PHOTO' && mediaId != null) {
        try {
          resolvedPhoto = await MediaPresentationResolver(
            api: widget.api,
            cache: _mediaCache,
          ).resolve(
            ownerUserId: owner,
            mediaId: mediaId,
          );
          if (!_sessionCurrent(version, owner)) return;
        } on ApiException {
          if (!_sessionCurrent(version, owner)) return;
          resolvedPhotoError = '照片暂时无法读取，可以重试。';
        } on TransportException {
          if (!_sessionCurrent(version, owner)) return;
          resolvedPhotoError = '网络暂时不可用，照片可以稍后重试。';
        } on ProtocolException {
          if (!_sessionCurrent(version, owner)) return;
          resolvedPhotoError = '照片读取信息暂时不可用。';
        }
      }

      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        memory = parsed;
        placeName = resolvedPlace;
        placeAddress = resolvedAddress;
        placeLatitude = resolvedLatitude;
        placeLongitude = resolvedLongitude;
        photoFile = resolvedPhoto;
        photoError = resolvedPhotoError;
        loading = false;
      });
    } on ApiException catch (exc) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        loading = false;
        error = exc.statusCode == 404
            ? '这条记忆已经不存在'
            : '这条记忆暂时无法打开，可以稍后重试';
      });
    } on ProtocolException {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        loading = false;
        error = '这条记忆的数据暂时无法识别，可以重新打开后再试';
      });
    } catch (_) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        loading = false;
        error = '这条记忆暂时无法打开，可以稍后重试';
      });
    }
  }

  Future<void> _refreshPhoto({bool manual = false}) async {
    final current = memory;
    final mediaId = current?.mediaId;
    final owner = widget.api.authenticatedUserId;
    if (current == null ||
        current.memoryType != 'PHOTO' ||
        mediaId == null ||
        owner == null ||
        owner.trim().isEmpty ||
        photoRefreshing) {
      return;
    }
    final version = widget.api.sessionVersion;
    setState(() {
      photoRefreshing = true;
      if (manual) photoError = null;
    });
    try {
      final resolved = await MediaPresentationResolver(
        api: widget.api,
        cache: _mediaCache,
      ).resolve(
        ownerUserId: owner,
        mediaId: mediaId,
      );
      if (!_sessionCurrent(version, owner) ||
          memory?.id != current.id ||
          memory?.mediaId != mediaId) {
        return;
      }
      setState(() {
        photoFile = resolved;
        photoError = null;
        photoRefreshing = false;
      });
    } on MediaUnavailableOffline {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        photoRefreshing = false;
        photoError = '这张照片尚未缓存，离线时暂时无法显示。';
      });
    } on TransportException {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        photoRefreshing = false;
        photoError = '网络暂时不可用；已缓存的照片仍可离线查看。';
      });
    } on ApiException {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        photoRefreshing = false;
        photoError = '照片暂时无法读取，可以重试。';
      });
    } on ProtocolException {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        photoRefreshing = false;
        photoError = '照片读取信息暂时不可用。';
      });
    } on MediaCacheException {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        photoRefreshing = false;
        photoError = '本地照片缓存暂时不可用，可以重试。';
      });
    }
  }

  Widget _photoCard(_MemoryDetailView current) {
    final local = photoFile;
    if (local == null) {
      return JiYiSectionCard(
        title: '照片',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(photoError ?? '正在准备照片…'),
            const SizedBox(height: JiYiSpacing.sm),
            OutlinedButton.icon(
              onPressed: photoRefreshing
                  ? null
                  : () => _refreshPhoto(manual: true),
              icon: photoRefreshing
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh),
              label: const Text('重新加载照片'),
            ),
          ],
        ),
      );
    }

    return JiYiSectionCard(
      title: '照片',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: widget.localPhotoRenderer?.call(
                  local,
                  ValueKey<String>(
                    'photo-local-${current.id}-${local.path}',
                  ),
                ) ??
                LocalMediaPresentationScope.maybeOf(context)?.renderer(
                  context,
                  local,
                  BoxFit.cover,
                ) ??
                _defaultLocalPhotoRenderer(
                  local,
                  ValueKey<String>(
                    'photo-local-${current.id}-${local.path}',
                  ),
                ),
          ),
          if (photoError != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            Text(photoError!),
          ],
          if (photoRefreshing) ...[
            const SizedBox(height: JiYiSpacing.sm),
            const LinearProgressIndicator(),
          ],
          const SizedBox(height: JiYiSpacing.sm),
          OutlinedButton.icon(
            onPressed: photoRefreshing ? null : () => _refreshPhoto(manual: true),
            icon: const Icon(Icons.refresh),
            label: const Text('重新加载照片'),
          ),
        ],
      ),
    );
  }

  Future<void> _edit() async {
    final current = memory;
    if (current == null || mutating) return;
    final draft = await showDialog<_MemoryDetailDraft>(
      context: context,
      builder: (_) => _MemoryDetailEditor(memory: current),
    );
    if (draft == null || !mounted) return;

    final version = widget.api.sessionVersion;
    final owner = widget.api.authenticatedUserId;
    setState(() {
      mutating = true;
      error = null;
      status = null;
    });
    try {
      await widget.api.updateMemory(
        current.id,
        expectedRevision: current.editRevision,
        title: draft.title,
        content: draft.content,
      );
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        mutating = false;
        status = '修改已保存';
      });
      await _load();
    } on ApiException catch (exc) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        mutating = false;
        error = exc.statusCode == 409
            ? '内容刚刚发生了变化，请重新打开后再试'
            : '修改暂时无法保存，可以稍后重试';
      });
    } catch (_) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        mutating = false;
        error = '修改暂时无法保存，可以稍后重试';
      });
    }
  }

  Future<void> _delete() async {
    final current = memory;
    if (current == null || mutating) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('删除这条记忆？'),
        content: const Text('删除后，这条记忆将不能再被找回，也不会继续用于后续查找。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton.icon(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
            onPressed: () => Navigator.of(context).pop(true),
            icon: const Icon(Icons.delete_outline),
            label: const Text('确认删除'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    final version = widget.api.sessionVersion;
    final owner = widget.api.authenticatedUserId;
    setState(() {
      mutating = true;
      error = null;
      status = null;
    });
    try {
      await widget.api.deleteMemory(current.id);
      if (!_sessionCurrent(version, owner)) return;
      if (current.mediaId != null && owner != null) {
        await _mediaCache.invalidateMedia(
          ownerUserId: owner,
          mediaId: current.mediaId!,
        );
      }
      if (!_sessionCurrent(version, owner)) return;
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (_) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        mutating = false;
        error = '删除暂时无法完成，可以稍后重试';
      });
    } catch (_) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() {
        mutating = false;
        error = '删除暂时无法完成，可以稍后重试';
      });
    }
  }

  Future<void> _createReminder() async {
    final current = memory;
    final owner = widget.api.authenticatedUserId;
    if (current == null || reminderBusy || owner == null || owner.trim().isEmpty) {
      return;
    }
    final version = widget.api.sessionVersion;
    setState(() {
      reminderBusy = true;
      error = null;
      status = null;
    });
    try {
      final message = await showMemoryReminderCreateFlow(
        context: context,
        api: widget.api,
        memoryId: current.id,
      );
      if (!_sessionCurrent(version, owner) || !mounted) return;
      if (message != null) {
        setState(() => status = message);
      }
    } on ApiException catch (exc) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() => error = exc.message);
    } catch (_) {
      if (!_sessionCurrent(version, owner)) return;
      setState(() => error = '暂时无法打开提醒创建流程');
    } finally {
      if (_sessionCurrent(version, owner)) {
        setState(() => reminderBusy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final current = memory;
    return V3PageScaffold(
      topBar: V3TopBar(
        title: '记忆详情',
        subtitle: current?.title ?? '回看你当时留下的内容。',
        onBack: () => Navigator.of(context).maybePop(),
        trailing: current == null
            ? null
            : PopupMenuButton<String>(
                key: const ValueKey('memory-detail-more'),
                tooltip: '更多操作',
                icon: const Icon(Icons.more_horiz),
                enabled: !mutating,
                onSelected: (action) {
                  switch (action) {
                    case 'edit':
                      unawaited(_edit());
                    case 'delete':
                      unawaited(_delete());
                  }
                },
                itemBuilder: (_) => const [
                  PopupMenuItem<String>(
                    key: ValueKey('memory-detail-more-edit'),
                    value: 'edit',
                    child: Text('编辑'),
                  ),
                  PopupMenuItem<String>(
                    key: ValueKey('memory-detail-more-delete'),
                    value: 'delete',
                    child: Text('删除'),
                  ),
                ],
              ),
      ),
      child: loading
          ? const V3StateSurface(
              variant: V3StateSurfaceVariant.loading,
              title: '正在打开记忆…',
              message: '正在读取这条记忆的真实内容。',
              icon: Icons.auto_stories_outlined,
            )
          : error != null && current == null
              ? Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    V3StateSurface(
                      variant: V3StateSurfaceVariant.error,
                      title: '这条记忆暂时不可用',
                      message: error!,
                      icon: Icons.auto_stories_outlined,
                      primaryAction: V3StateAction(
                        label: '重新打开',
                        icon: Icons.refresh,
                        onPressed: _load,
                      ),
                    ),
                  ],
                )
              : current == null
                  ? const V3StateSurface(
                      variant: V3StateSurfaceVariant.empty,
                      icon: Icons.auto_stories_outlined,
                      title: '这条记忆不可用',
                      message: '可以返回记忆页重新查找。',
                    )
                  : _ready(current),
    );
  }

  Widget _ready(_MemoryDetailView current) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (error != null) ...[
          JiYiStatusBanner(kind: JiYiStatusKind.error, message: error!),
          const SizedBox(height: JiYiSpacing.sm),
        ],
        if (status != null) ...[
          JiYiStatusBanner(kind: JiYiStatusKind.success, message: status!),
          const SizedBox(height: JiYiSpacing.sm),
        ],
        if (current.memoryType == 'PHOTO') ...[
          _photoCard(current),
          const SizedBox(height: JiYiSpacing.md),
        ],
        if (current.placeId != null &&
            placeLatitude != null &&
            placeLongitude != null) ...[
          JiYiPlaceMap(
            latitude: placeLatitude,
            longitude: placeLongitude,
            name: placeName ?? '已关联地点',
            address: placeAddress,
            privacyAccepted: _mapPrivacyAccepted,
          ),
          if (!_mapPrivacyAccepted) ...[
            const SizedBox(height: JiYiSpacing.sm),
            OutlinedButton.icon(
              key: const ValueKey('memory-amap-privacy-accept'),
              onPressed: _acceptMapPrivacy,
              icon: const Icon(Icons.map_outlined),
              label: const Text('同意地图服务隐私说明并启用地图'),
            ),
          ],
          const SizedBox(height: JiYiSpacing.md),
        ],
        JiYiSectionCard(
          title: '记录',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _DetailRow(label: '类型', value: _memoryTypeLabel(current.memoryType)),
              _DetailRow(label: '时间', value: _formatDateTime(current.occurredAt)),
              if (current.placeId != null)
                _DetailRow(label: '地点', value: placeName ?? '已关联地点'),
              const SizedBox(height: JiYiSpacing.sm),
              Text(
                current.content,
                style: Theme.of(context).textTheme.bodyLarge?.copyWith(height: 1.6),
              ),
            ],
          ),
        ),
        const SizedBox(height: JiYiSpacing.md),
        JiYiSectionCard(
          title: '管理',
          subtitle: '编辑会保留原始记录；删除会影响后续查找。',
          child: Wrap(
            spacing: JiYiSpacing.sm,
            runSpacing: JiYiSpacing.xs,
            children: [
              OutlinedButton.icon(
                onPressed: mutating ? null : _edit,
                icon: const Icon(Icons.edit_outlined),
                label: const Text('编辑'),
              ),
              OutlinedButton.icon(
                key: const ValueKey('memory-reminder-entry'),
                onPressed: mutating || reminderBusy ? null : _createReminder,
                icon: reminderBusy
                    ? const SizedBox.square(
                        dimension: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.notifications_none_outlined),
                label: Text(reminderBusy ? '打开提醒…' : '设置提醒'),
              ),
              TextButton.icon(
                onPressed: mutating ? null : _delete,
                icon: const Icon(Icons.delete_outline),
                label: const Text('删除'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _MemoryDetailDraft {
  const _MemoryDetailDraft({required this.title, required this.content});

  final String? title;
  final String content;
}

class _MemoryDetailEditor extends StatefulWidget {
  const _MemoryDetailEditor({required this.memory});

  final _MemoryDetailView memory;

  @override
  State<_MemoryDetailEditor> createState() => _MemoryDetailEditorState();
}

class _MemoryDetailEditorState extends State<_MemoryDetailEditor> {
  late final TextEditingController title =
      TextEditingController(text: widget.memory.title ?? '');
  late final TextEditingController content =
      TextEditingController(text: widget.memory.content);
  String? error;

  @override
  void dispose() {
    title.dispose();
    content.dispose();
    super.dispose();
  }

  void _submit() {
    final body = content.text.trim();
    final heading = title.text.trim();
    if (body.isEmpty) {
      setState(() => error = '记忆内容不能为空');
      return;
    }
    Navigator.of(context).pop(
      _MemoryDetailDraft(
        title: heading.isEmpty ? null : heading,
        content: body,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('编辑记忆'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: title,
              maxLength: 240,
              decoration: const InputDecoration(labelText: '标题（可选）'),
            ),
            TextField(
              controller: content,
              minLines: 4,
              maxLines: 8,
              maxLength: 20000,
              decoration: InputDecoration(
                labelText: '内容',
                alignLabelWithHint: true,
                errorText: error,
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('取消'),
        ),
        FilledButton(onPressed: _submit, child: const Text('保存')),
      ],
    );
  }
}

class _DetailRow extends StatelessWidget {
  const _DetailRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: JiYiSpacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 64,
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}

class _MemoryDetailView {
  const _MemoryDetailView({
    required this.id,
    required this.memoryType,
    required this.title,
    required this.content,
    required this.occurredAt,
    required this.placeId,
    required this.mediaId,
    required this.editRevision,
  });

  final String id;
  final String memoryType;
  final String? title;
  final String content;
  final String occurredAt;
  final String? placeId;
  final String? mediaId;
  final int editRevision;

  static final RegExp _uuid = RegExp(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    caseSensitive: false,
  );

  factory _MemoryDetailView.parse(
    Map<String, dynamic> raw, {
    required String expectedId,
    required String expectedOwnerId,
  }) {
    String requiredUuid(String key) {
      final value = raw[key];
      if (value is! String || !_uuid.hasMatch(value)) {
        throw ProtocolException('记忆数据格式不正确');
      }
      return value;
    }

    final id = requiredUuid('id');
    final ownerId = requiredUuid('user_id');
    if (id.toLowerCase() != expectedId.toLowerCase() ||
        ownerId.toLowerCase() != expectedOwnerId.toLowerCase()) {
      throw ProtocolException('记忆归属不匹配');
    }

    final type = raw['memory_type'];
    final content = raw['content'];
    final occurredAt = raw['occurred_at'];
    final revision = raw['edit_revision'];
    final title = raw['title'];
    final place = raw['place_id'];
    final metadata = raw['metadata_json'];
    String? mediaId;
    if (metadata != null && metadata is! Map<String, dynamic>) {
      throw ProtocolException('记忆数据格式不正确');
    }
    if (metadata is Map<String, dynamic> && metadata['media_id'] != null) {
      final candidate = metadata['media_id'];
      if (candidate is! String || !_uuid.hasMatch(candidate)) {
        throw ProtocolException('记忆数据格式不正确');
      }
      mediaId = candidate;
    }
    if (type is! String ||
        type.trim().isEmpty ||
        content is! String ||
        content.trim().isEmpty ||
        occurredAt is! String ||
        DateTime.tryParse(occurredAt) == null ||
        revision is! int ||
        revision < 0 ||
        (title != null && title is! String) ||
        (place != null && (place is! String || !_uuid.hasMatch(place))) ||
        (type == 'PHOTO' && mediaId == null)) {
      throw ProtocolException('记忆数据格式不正确');
    }

    return _MemoryDetailView(
      id: id,
      memoryType: type,
      title: title is String && title.trim().isNotEmpty ? title.trim() : null,
      content: content.trim(),
      occurredAt: occurredAt,
      placeId: place as String?,
      mediaId: mediaId,
      editRevision: revision,
    );
  }
}

double? _memoryPlaceCoordinate(
  Object? value, {
  required bool latitudeAxis,
}) {
  if (value == null) return null;
  if (value is! num || !value.isFinite) return null;
  final coordinate = value.toDouble();
  final max = latitudeAxis ? 90.0 : 180.0;
  if (coordinate < -max || coordinate > max) return null;
  return coordinate;
}

String _memoryTypeLabel(String value) => switch (value) {
      'NOTE' => '文字记录',
      'VOICE' => '语音记录',
      'PHOTO' => '照片记录',
      'PLACE' => '地点记录',
      'OBJECT_LOCATION' => '物品位置',
      'REMINDER' => '提醒记录',
      'EVENT' => '事件记录',
      _ => '记忆',
    };

String _formatDateTime(String value) {
  final parsed = DateTime.tryParse(value);
  if (parsed == null) return '时间未知';
  final local = parsed.toLocal();
  String two(int v) => v.toString().padLeft(2, '0');
  return '${local.year}-${two(local.month)}-${two(local.day)} '
      '${two(local.hour)}:${two(local.minute)}';
}


Widget _defaultLocalPhotoRenderer(File file, Key key) {
  return Image.file(
    file,
    key: key,
    fit: BoxFit.contain,
    errorBuilder: (context, error, stackTrace) {
      return Container(
        constraints: const BoxConstraints(minHeight: 160),
        alignment: Alignment.center,
        child: const Text('本地照片缓存已损坏，请重新加载。'),
      );
    },
  );
}
