// ignore_for_file: prefer_interpolation_to_compose_strings

import 'package:flutter/material.dart';

import 'life_models.dart';
import 'people_models.dart';

const Map<String, String> lifeEventLabels = {
  'TRAVEL': '旅行',
  'MEDICAL': '医疗',
  'GATHERING': '聚会',
  'WORK': '工作',
  'EDUCATION': '学习',
  'FAMILY': '家庭',
  'OTHER': '其他',
};

const Map<String, String> lifeStageLabels = {
  'WORK': '工作',
  'EDUCATION': '学习',
  'FAMILY': '家庭',
  'RESIDENCE': '居住',
  'TRAVEL': '旅行',
  'OTHER': '其他',
};

class LifeEventDraft {
  const LifeEventDraft({
    required this.kind,
    required this.title,
    required this.customLabel,
    required this.note,
    required this.startedAt,
    required this.endedAt,
    required this.placeId,
  });

  final String kind;
  final String title;
  final String customLabel;
  final String note;
  final String startedAt;
  final String? endedAt;
  final String? placeId;
}

class LifeStageDraft {
  const LifeStageDraft({
    required this.kind,
    required this.title,
    required this.customLabel,
    required this.note,
    required this.startedAt,
    required this.endedAt,
  });

  final String kind;
  final String title;
  final String customLabel;
  final String note;
  final String startedAt;
  final String? endedAt;
}

Future<DateTime?> _pickDateTime(BuildContext context, DateTime initial) async {
  final date = await showDatePicker(
    context: context,
    initialDate: initial,
    firstDate: DateTime(1),
    lastDate: DateTime(9998, 12, 31),
  );
  if (date == null || !context.mounted) return null;
  final time = await showTimePicker(
    context: context,
    initialTime: TimeOfDay.fromDateTime(initial),
  );
  if (time == null) return null;
  return DateTime(date.year, date.month, date.day, time.hour, time.minute);
}

String _displayDateTime(DateTime value) {
  final local = value.toLocal();
  String two(int value) => value.toString().padLeft(2, '0');
  return local.year.toString().padLeft(4, '0') +
      '-' +
      two(local.month) +
      '-' +
      two(local.day) +
      ' ' +
      two(local.hour) +
      ':' +
      two(local.minute);
}

class LifeEventEditorDialog extends StatefulWidget {
  const LifeEventEditorDialog({
    super.key,
    required this.places,
    this.initial,
  });

  final List<V2PlacePickerItem> places;
  final V2LifeEvent? initial;

  @override
  State<LifeEventEditorDialog> createState() => _LifeEventEditorDialogState();
}

class _LifeEventEditorDialogState extends State<LifeEventEditorDialog> {
  late String kind = widget.initial?.kind ?? 'WORK';
  late final TextEditingController title =
      TextEditingController(text: widget.initial?.title ?? '');
  late final TextEditingController custom =
      TextEditingController(text: widget.initial?.customLabel ?? '');
  late final TextEditingController note =
      TextEditingController(text: widget.initial?.note ?? '');
  late DateTime started = widget.initial == null
      ? DateTime.now()
      : DateTime.parse(widget.initial!.startedAt).toLocal();
  late DateTime? ended = widget.initial?.endedAt == null
      ? null
      : DateTime.parse(widget.initial!.endedAt!).toLocal();
  late String? placeId = widget.initial?.placeId;
  String? error;

  @override
  void dispose() {
    title.dispose();
    custom.dispose();
    note.dispose();
    super.dispose();
  }

  Future<void> pickStart() async {
    final value = await _pickDateTime(context, started);
    if (value != null && mounted) setState(() => started = value);
  }

  Future<void> pickEnd() async {
    final value = await _pickDateTime(context, ended ?? started);
    if (value != null && mounted) setState(() => ended = value);
  }

  void submit() {
    final normalizedTitle = title.text.trim();
    final customText = custom.text.trim();
    final noteText = note.text.trim();
    if (normalizedTitle.isEmpty || normalizedTitle.length > 240) {
      setState(() => error = '事件标题需为 1–240 个字符');
      return;
    }
    if (kind == 'OTHER' ? customText.isEmpty : customText.isNotEmpty) {
      setState(() => error = '自定义类型只允许且必须用于“其他”');
      return;
    }
    if (customText.length > 120 || noteText.length > 5000) {
      setState(() => error = '自定义类型或备注过长');
      return;
    }
    if (ended != null && ended!.isBefore(started)) {
      setState(() => error = '结束时间不能早于开始时间');
      return;
    }
    Navigator.of(context).pop(
      LifeEventDraft(
        kind: kind,
        title: normalizedTitle,
        customLabel: customText,
        note: noteText,
        startedAt: started.toUtc().toIso8601String(),
        endedAt: ended?.toUtc().toIso8601String(),
        placeId: placeId,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final placeValues = <String?>[null, ...widget.places.map((item) => item.id)];
    return AlertDialog(
      title: Text(widget.initial == null ? '新建人生事件' : '编辑人生事件'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            DropdownButtonFormField<String>(
              initialValue: kind,
              decoration: const InputDecoration(labelText: '事件类型'),
              items: [
                for (final entry in lifeEventLabels.entries)
                  DropdownMenuItem(value: entry.key, child: Text(entry.value)),
              ],
              onChanged: (value) {
                if (value != null) {
                  setState(() {
                    kind = value;
                    if (kind != 'OTHER') custom.clear();
                  });
                }
              },
            ),
            if (kind == 'OTHER')
              TextField(
                controller: custom,
                maxLength: 120,
                decoration: const InputDecoration(labelText: '自定义类型'),
              ),
            TextField(
              controller: title,
              maxLength: 240,
              decoration: const InputDecoration(labelText: '事件标题'),
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('开始时间'),
              subtitle: Text(_displayDateTime(started)),
              trailing: const Icon(Icons.edit_calendar_outlined),
              onTap: pickStart,
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('结束时间'),
              subtitle: Text(ended == null ? '未设置' : _displayDateTime(ended!)),
              trailing: Wrap(
                children: [
                  IconButton(
                    tooltip: '选择结束时间',
                    onPressed: pickEnd,
                    icon: const Icon(Icons.edit_calendar_outlined),
                  ),
                  if (ended != null)
                    IconButton(
                      tooltip: '清除结束时间',
                      onPressed: () => setState(() => ended = null),
                      icon: const Icon(Icons.clear),
                    ),
                ],
              ),
            ),
            DropdownButtonFormField<String?>(
              initialValue: placeValues.contains(placeId) ? placeId : null,
              decoration: const InputDecoration(labelText: '地点（可选）'),
              items: [
                const DropdownMenuItem<String?>(
                  value: null,
                  child: Text('不关联地点'),
                ),
                for (final place in widget.places)
                  DropdownMenuItem<String?>(
                    value: place.id,
                    child: Text(place.name),
                  ),
              ],
              onChanged: (value) => setState(() => placeId = value),
            ),
            TextField(
              controller: note,
              maxLength: 5000,
              minLines: 2,
              maxLines: 4,
              decoration: const InputDecoration(labelText: '备注（可选）'),
            ),
            if (error != null) Text(error!),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('取消')),
        FilledButton(onPressed: submit, child: const Text('保存')),
      ],
    );
  }
}

class LifeStageEditorDialog extends StatefulWidget {
  const LifeStageEditorDialog({super.key, this.initial});

  final V2LifeStage? initial;

  @override
  State<LifeStageEditorDialog> createState() => _LifeStageEditorDialogState();
}

class _LifeStageEditorDialogState extends State<LifeStageEditorDialog> {
  late String kind = widget.initial?.kind ?? 'WORK';
  late final TextEditingController title =
      TextEditingController(text: widget.initial?.title ?? '');
  late final TextEditingController custom =
      TextEditingController(text: widget.initial?.customLabel ?? '');
  late final TextEditingController note =
      TextEditingController(text: widget.initial?.note ?? '');
  late DateTime started = widget.initial == null
      ? DateTime.now()
      : DateTime.parse(widget.initial!.startedAt).toLocal();
  late DateTime? ended = widget.initial?.endedAt == null
      ? null
      : DateTime.parse(widget.initial!.endedAt!).toLocal();
  String? error;

  @override
  void dispose() {
    title.dispose();
    custom.dispose();
    note.dispose();
    super.dispose();
  }

  Future<void> pickStart() async {
    final value = await _pickDateTime(context, started);
    if (value != null && mounted) setState(() => started = value);
  }

  Future<void> pickEnd() async {
    final value = await _pickDateTime(context, ended ?? started);
    if (value != null && mounted) setState(() => ended = value);
  }

  void submit() {
    final normalizedTitle = title.text.trim();
    final customText = custom.text.trim();
    final noteText = note.text.trim();
    if (normalizedTitle.isEmpty || normalizedTitle.length > 240) {
      setState(() => error = '阶段标题需为 1–240 个字符');
      return;
    }
    if (kind == 'OTHER' ? customText.isEmpty : customText.isNotEmpty) {
      setState(() => error = '自定义类型只允许且必须用于“其他”');
      return;
    }
    if (customText.length > 120 || noteText.length > 5000) {
      setState(() => error = '自定义类型或备注过长');
      return;
    }
    if (ended != null && ended!.isBefore(started)) {
      setState(() => error = '结束时间不能早于开始时间');
      return;
    }
    Navigator.of(context).pop(
      LifeStageDraft(
        kind: kind,
        title: normalizedTitle,
        customLabel: customText,
        note: noteText,
        startedAt: started.toUtc().toIso8601String(),
        endedAt: ended?.toUtc().toIso8601String(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.initial == null ? '新建人生阶段' : '编辑人生阶段'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            DropdownButtonFormField<String>(
              initialValue: kind,
              decoration: const InputDecoration(labelText: '阶段类型'),
              items: [
                for (final entry in lifeStageLabels.entries)
                  DropdownMenuItem(value: entry.key, child: Text(entry.value)),
              ],
              onChanged: (value) {
                if (value != null) {
                  setState(() {
                    kind = value;
                    if (kind != 'OTHER') custom.clear();
                  });
                }
              },
            ),
            if (kind == 'OTHER')
              TextField(
                controller: custom,
                maxLength: 120,
                decoration: const InputDecoration(labelText: '自定义类型'),
              ),
            TextField(
              controller: title,
              maxLength: 240,
              decoration: const InputDecoration(labelText: '阶段标题'),
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('开始时间'),
              subtitle: Text(_displayDateTime(started)),
              onTap: pickStart,
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('结束时间'),
              subtitle: Text(ended == null ? '开放' : _displayDateTime(ended!)),
              trailing: Wrap(
                children: [
                  IconButton(
                    tooltip: '选择结束时间',
                    onPressed: pickEnd,
                    icon: const Icon(Icons.edit_calendar_outlined),
                  ),
                  if (ended != null)
                    IconButton(
                      tooltip: '清除结束时间',
                      onPressed: () => setState(() => ended = null),
                      icon: const Icon(Icons.clear),
                    ),
                ],
              ),
            ),
            TextField(
              controller: note,
              maxLength: 5000,
              minLines: 2,
              maxLines: 4,
              decoration: const InputDecoration(labelText: '备注（可选）'),
            ),
            if (error != null) Text(error!),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('取消')),
        FilledButton(onPressed: submit, child: const Text('保存')),
      ],
    );
  }
}
