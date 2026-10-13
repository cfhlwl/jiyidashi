import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'photo_import_batch.dart';
import 'photo_import_journal.dart';
import 'offline_queue.dart';
import 'photo_import_metadata.dart';

/// Explicit gallery picker flow. Nothing is enumerated or transmitted during
/// page build; all uploads follow user selection and a second Submit action.
/// Remaining offline/resume work is tracked by Issue #260.
class PhotoImportPage extends StatefulWidget {
  const PhotoImportPage({
    super.key,
    required this.api,
    this.picker,
    this.offlineQueue,
  });

  final JiYiApiClient api;
  final PhotoImportPicker? picker;
  final OfflineQueueStore? offlineQueue;

  @override
  State<PhotoImportPage> createState() => _PhotoImportPageState();
}

class _PhotoImportPageState extends State<PhotoImportPage> {
  late final String? _pageOwner = widget.api.authenticatedUserId;
  late final int _pageSessionVersion = widget.api.sessionVersion;
  late final PhotoImportPicker _picker = widget.picker ?? PhotoImportPicker();
  late final PhotoImportJournal? _journal = widget.offlineQueue == null ||
          _pageOwner == null
      ? null
      : PhotoImportJournal(store: widget.offlineQueue!, ownerUserId: _pageOwner);
  PhotoImportSelection? _selection;
  PhotoImportBatchCoordinator? _batch;
  bool _picking = false;
  int _selectionEpoch = 0;
  String? _message;

  @override
  void initState() {
    super.initState();
    if (_journal != null) {
      unawaited(_restoreDurableImport());
    }
  }

  Future<void> _restoreDurableImport() async {
    final restoringEpoch = _selectionEpoch;
    try {
      final journal = _journal!;
      final existing = await journal.list();
      final active = existing.where((row) =>
          row.status != OfflineQueueStatus.completed &&
          row.status != OfflineQueueStatus.cancelled);
      final restored = <PhotoImportBatchItem>[];
      for (final row in active) {
        final photo = await journal.selectedFrom(row);
        restored.add(PhotoImportBatchItem(
          photo,
          clientUploadId: row.clientUuid,
          state: PhotoImportBatchCoordinator.isUploadActive(
                  _pageOwner!, row.clientUuid)
              ? PhotoImportItemState.uploading
              : row.status == OfflineQueueStatus.failed
                  ? PhotoImportItemState.failed
                  : PhotoImportItemState.waiting,
        ));
      }
      if (!mounted || widget.api.authenticatedUserId != _pageOwner ||
          widget.api.sessionVersion != _pageSessionVersion ||
          restoringEpoch != _selectionEpoch || _picking ||
          _selection != null || restored.isEmpty) {
        return;
      }
      setState(() {
        _selection = PhotoImportSelection(
          selected: List.unmodifiable(restored.map((i) => i.selected)),
          failedNames: const [],
          duplicates: 0,
        );
        _batch = PhotoImportBatchCoordinator.restored(
          api: widget.api,
          restoredItems: restored,
          journal: journal,
        );
        _message = restored.any((item) =>
                PhotoImportBatchCoordinator.isUploadActive(
                    _pageOwner!, item.clientUploadId))
            ? '仍有照片正在上传；请勿重复提交，完成后重新打开此页面查看结果。'
            : '已恢复 ${restored.length} 张待续传照片。确认后才会继续上传。';
      });
    } catch (_) {
      if (mounted && widget.api.authenticatedUserId == _pageOwner &&
          widget.api.sessionVersion == _pageSessionVersion &&
          restoringEpoch == _selectionEpoch && !_picking &&
          _selection == null) {
        setState(() => _message = '部分待续传照片暂不可用，可重新选择照片。');
      }
    }
  }

  bool get _busy => _picking || _batch?.isRunning == true;

  Future<void> _choose() async {
    if (_busy) return;
    final requestedOwner = widget.api.authenticatedUserId;
    final requestedVersion = widget.api.sessionVersion;
    if (requestedOwner == null || requestedOwner.isEmpty) return;
    _batch?.stopAfterCurrentFile();
    final selectionEpoch = ++_selectionEpoch;
    setState(() {
      _picking = true;
      _message = null;
    });
    try {
      final selected = await _picker.pick();
      if (!mounted) return;
      if (widget.api.authenticatedUserId != requestedOwner ||
          widget.api.sessionVersion != requestedVersion ||
          selectionEpoch != _selectionEpoch) {
        setState(() => _message = '选择照片期间账号已变化，请在当前账号重新选择。');
        return;
      }
      final next = PhotoImportBatchCoordinator(
        api: widget.api,
        selection: selected,
        journal: _journal,
      );
      setState(() {
        _selection = selected;
        _batch = next;
      });
    } catch (_) {
      if (mounted) {
        setState(() => _message = '读取照片失败，请检查系统照片选择器或云端原图下载状态。');
      }
    } finally {
      if (mounted && selectionEpoch == _selectionEpoch) {
        setState(() => _picking = false);
      }
    }
  }

  Future<void> _submit() async {
    final batch = _batch;
    if (batch == null || _busy) return;
    setState(() => _message = null);
    try {
      await batch.submit(onUpdate: (_) {
        if (mounted) setState(() {});
      });
      if (mounted) {
        setState(() {
          _message = batch.failedCount > 0
              ? '已保存 ${batch.savedCount} 张，失败 ${batch.failedCount} 张。可重试失败项。'
              : '已保存 ${batch.savedCount} 张到当前账号的真实照片记忆。';
        });
      }
    } on ProtocolException {
      if (mounted) {
        setState(() => _message = '账号或登录状态已变化，当前批次已经停止，请重新选择。');
      }
    } catch (_) {
      if (mounted) setState(() => _message = '照片导入暂停，请检查网络后重试。');
    }
    if (mounted) setState(() {});
  }

  Future<void> _withdraw() async {
    final batch = _batch;
    if (batch == null || _busy) return;
    try {
      await batch.withdrawPending(onUpdate: (_) {
        if (mounted) setState(() {});
      });
      if (mounted) {
        setState(() => _message = '已撤回未提交的照片，不影响已保存的记忆。');
      }
    } catch (_) {
      if (mounted) {
        setState(() => _message = '撤回过程中遇到问题，请稍后重试。');
      }
    }
  }

  @override
  void dispose() {
    _batch?.stopAfterCurrentFile();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (widget.api.authenticatedUserId != _pageOwner ||
        widget.api.sessionVersion != _pageSessionVersion) {
      // The old account's selected thumbnails and filenames are private.
      // Do not leave them visible if this route outlives an auth rebind.
      return Scaffold(
        appBar: AppBar(title: const Text('导入已有照片')),
        body: Center(
          child: TextButton(
            key: const ValueKey('photo-import-owner-changed'),
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('登录状态已变化，请返回重新选择照片'),
          ),
        ),
      );
    }
    final batch = _batch;
    final selected = _selection;
    return Scaffold(
      appBar: AppBar(title: const Text('导入已有照片')),
      body: ListView(
        key: const ValueKey('photo-import-page'),
        padding: const EdgeInsets.all(16),
        children: [
          const Text(
            '只有你通过系统选择器主动选中的照片才会被处理。点击“开始导入”后，将上传所选原图及随原图附带的 EXIF/GPS 元数据，用来建立你自己的照片记忆。',
          ),
          const SizedBox(height: 8),
          const Text(
            '拍摄时间与地点没有足够证据时标记为未知；照片 GPS 仅作未核实线索，不生成行程轨迹。可以跳过或稍后再导入。',
          ),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            key: const ValueKey('photo-import-select'),
            onPressed: _busy ? null : _choose,
            icon: const Icon(Icons.photo_library_outlined),
            label: Text(_picking ? '正在读取所选照片…' : '选择照片（最多20张）'),
          ),
          if (selected != null) ...[
            const SizedBox(height: 12),
            Text(
              '已选择 ${selected.selected.length} 张，重复 ${selected.duplicates} 张，'
              '暂不可用 ${selected.failedNames.length} 张。',
            ),
            const SizedBox(height: 8),
            for (var index = 0; index < selected.selected.length; index++)
              _ImportedPhotoRow(
                key: ValueKey('photo-import-row-$index'),
                item: selected.selected[index],
                state: batch?.items[index].state,
              ),
            if (selected.selected.isNotEmpty) ...[
              const SizedBox(height: 12),
              FilledButton(
                key: const ValueKey('photo-import-submit'),
                onPressed: _busy ? null : _submit,
                child: Text(batch?.failedCount == 0 && batch?.savedCount == 0
                    ? '开始导入所选照片'
                    : '继续 / 重试尚未保存的照片'),
              ),
              if (batch?.items.any((item) =>
                      item.state == PhotoImportItemState.waiting ||
                      item.state == PhotoImportItemState.failed) == true)
                TextButton.icon(
                  key: const ValueKey('photo-import-withdraw'),
                  onPressed: _busy ? null : _withdraw,
                  icon: const Icon(Icons.remove_circle_outline),
                  label: const Text('撤回未提交的照片'),
                ),
              if (batch?.isRunning == true)
                OutlinedButton(
                  key: const ValueKey('photo-import-stop'),
                  onPressed: () {
                    batch!.stopAfterCurrentFile();
                    setState(() => _message = '将完成当前文件后停止，不撤销已经保存的照片。');
                  },
                  child: const Text('停止后续导入'),
                ),
            ],
          ],
          if (_message != null) ...[
            const SizedBox(height: 12),
            Text(_message!, key: const ValueKey('photo-import-message')),
          ],
          const SizedBox(height: 16),
          TextButton(
            key: const ValueKey('photo-import-close'),
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('返回'),
          ),
        ],
      ),
    );
  }
}

class _ImportedPhotoRow extends StatelessWidget {
  const _ImportedPhotoRow({super.key, required this.item, this.state});

  final SelectedPhotoImport item;
  final PhotoImportItemState? state;

  @override
  Widget build(BuildContext context) {
    final e = item.evidence;
    final timeLabel = e.captureTimeUtc != null
        ? '拍摄时间（含时区）：${e.localCaptureTime}'
        : e.localCaptureTime != null
            ? '拍摄本地时间：${e.localCaptureTime}（时区未知）'
            : '拍摄时间未知';
    final locationLabel = e.hasGps ? '含照片 GPS 线索（未核实）' : '地点未知';
    final statusLabel = switch (state) {
      PhotoImportItemState.uploading => '上传中',
      PhotoImportItemState.verifying => '验证原图中',
      PhotoImportItemState.saving => '保存记忆中',
      PhotoImportItemState.saved => '已保存记忆',
      PhotoImportItemState.failed => '失败，可重试',
      PhotoImportItemState.cancelled => '已撤回',
      _ => '待导入',
    };
    return ListTile(
      leading: SizedBox(
        width: 52,
        height: 52,
        child: Image.file(
          File(item.path),
          fit: BoxFit.cover,
          errorBuilder: (_, _, _) =>
              const Icon(Icons.image_not_supported_outlined),
        ),
      ),
      title: Text(item.originalFilename, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text('$timeLabel · $locationLabel\n$statusLabel'),
      isThreeLine: true,
    );
  }
}
