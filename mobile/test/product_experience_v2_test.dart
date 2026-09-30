import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

class _UiCopyLeak {
  const _UiCopyLeak(this.path, this.value, this.reason);

  final String path;
  final String value;
  final String reason;

  @override
  String toString() => '$path: $reason -> "$value"';
}

List<File> _productionUiFiles() {
  final files = Directory('lib')
      .listSync(recursive: true)
      .whereType<File>()
      .where((file) => file.path.endsWith('.dart'))
      .where((file) {
        final source = file.readAsStringSync();
        final importsFlutterUi =
            source.contains("package:flutter/material.dart") ||
            source.contains("package:flutter/widgets.dart");
        final rendersUi =
            source.contains('Widget build(') ||
            source.contains('showDialog<') ||
            source.contains('showModalBottomSheet<');
        return importsFlutterUi && rendersUi;
      })
      .toList()
    ..sort((a, b) => a.path.compareTo(b.path));
  return files;
}

List<String> _visibleUiLiterals(String source) {
  final literals = <String>[];
  final patterns = [
    // Only direct literals are production copy. Do not walk forward through an
    // arbitrary expression, otherwise internal switch values can be mistaken
    // for a title/message that happens to precede them in the source.
    RegExp(
      r'''Text(?:\.[A-Za-z]+)?\(\s*(?:const\s+)?(?:'([^']*)'|"([^"]*)")''',
      multiLine: true,
    ),
    RegExp(
      r'''(?:title|subtitle|message|label|eyebrow|hintText|helperText|errorText|tooltip|semanticLabel|text)\s*:\s*(?:const\s+Text\(\s*)?(?:'([^']*)'|"([^"]*)")''',
      multiLine: true,
    ),
  ];

  for (final pattern in patterns) {
    for (final match in pattern.allMatches(source)) {
      final groups = match.groups([1, 2]).whereType<String>().toList();
      final value = groups.isEmpty ? null : groups.first;
      if (value != null && value.trim().isNotEmpty) {
        literals.add(value);
      }
    }
  }
  return literals;
}

List<_UiCopyLeak> _productionLanguageLeaks() {
  final leaks = <_UiCopyLeak>[];
  final forbiddenVocabulary = <MapEntry<RegExp, String>>[
    MapEntry(RegExp(r'SEC-', caseSensitive: false), 'security/internal ticket token'),
    MapEntry(RegExp(r'\bprovider\b', caseSensitive: false), 'provider implementation term'),
    MapEntry(RegExp(r'\bprovenance\b', caseSensitive: false), 'provenance implementation term'),
    MapEntry(RegExp(r'citation\s*slot', caseSensitive: false), 'citation-slot implementation term'),
    MapEntry(RegExp(r'\bas_of\b', caseSensitive: false), 'raw as_of field'),
    MapEntry(RegExp(r'\bMemory\b'), 'raw Memory model name'),
    MapEntry(RegExp(r'\bEvidence\b'), 'raw Evidence model name'),
    MapEntry(RegExp(r'\bVisit\b'), 'raw Visit model name'),
    MapEntry(RegExp(r'\bGraph\b'), 'raw Graph model name'),
    MapEntry(RegExp(r'\bLifeEvent\b'), 'raw LifeEvent model name'),
    MapEntry(RegExp(r'\bLifeStage\b'), 'raw LifeStage model name'),
  ];
  final rawEnums = RegExp(
    r'\b(?:UNKNOWN|CONFIRMED|INFERRED|UNAVAILABLE|READY|FAILED|ERROR|LOADING|ACTIVE|PAUSED|PENDING|DENIED|GRANTED|ALLOWED|BLOCKED|REVOKED|EXPIRED|STALE|NOTE|VOICE|PHOTO|PLACE|OBJECT_LOCATION|REMINDER|EVENT|VISIT|MEMORY|PERSON|LIFE_EVENT|LIFE_STAGE)\b',
  );
  final directRawUiExpression = RegExp(
    r'''(?:Text(?:\.[A-Za-z]+)?\(|(?:title|subtitle|message|label|eyebrow|hintText|helperText|errorText|tooltip|semanticLabel|text)\s*:)\s*(?:(?:[A-Za-z_]\w*\.)+(?:status|state|trust|certainty|memoryType|visitSource|stageKind|relationKind)|(?:certainty|memoryType|visitSource|stageKind|relationKind))\b''',
    multiLine: true,
  );
  final interpolatedRawUiValue = RegExp(
    r'''(?:\$|\$\{)\s*(?:(?:[A-Za-z_]\w*\.)+(?:status|state|trust|certainty|memoryType|visitSource|stageKind|relationKind)|(?:certainty|memoryType|visitSource|stageKind|relationKind))\s*\}?''',
    caseSensitive: false,
  );

  for (final file in _productionUiFiles()) {
    final source = file.readAsStringSync();
    for (final literal in _visibleUiLiterals(source)) {
      for (final forbidden in forbiddenVocabulary) {
        if (forbidden.key.hasMatch(literal)) {
          leaks.add(_UiCopyLeak(file.path, literal, forbidden.value));
        }
      }
      final enumMatch = rawEnums.firstMatch(literal);
      if (enumMatch != null) {
        leaks.add(
          _UiCopyLeak(
            file.path,
            literal,
            'raw trust/status/domain enum ${enumMatch.group(0)}',
          ),
        );
      }
      if (interpolatedRawUiValue.hasMatch(literal)) {
        leaks.add(
          _UiCopyLeak(file.path, literal, 'raw trust/status value interpolation'),
        );
      }
    }

    for (final match in directRawUiExpression.allMatches(source)) {
      leaks.add(
        _UiCopyLeak(
          file.path,
          match.group(0)!.replaceAll(RegExp(r'\s+'), ' ').trim(),
          'raw trust/status expression passed directly to visible UI',
        ),
      );
    }
  }
  return leaks;
}

void main() {
  test('Flutter Product Experience V2 uses human-facing People and Life language', () {
    final people = File('lib/v2/people_page.dart').readAsStringSync();
    final life = File('lib/v2/life_page.dart').readAsStringSync();
    final home = File('lib/v2/v2_home_page.dart').readAsStringSync();
    final shell = File('lib/stage1_app.dart').readAsStringSync();

    expect(people, contains('重要的人'));
    expect(people, contains('最近相关的记忆'));
    expect(people, isNot(contains('Person ↔ Memory')));
    expect(people, isNot(contains('row.link.relationKind')));

    expect(life, contains('我的人生'));
    expect(life, contains('人生经历'));
    expect(life, contains('人生故事'));
    expect(life, isNot(contains('CRUD')));
    expect(life, isNot(contains('LifeEvent 显式关联')));
    expect(life, isNot(contains('Memory 证据')));
    expect(life, isNot(contains('服务端确定性投影')));
    expect(life, isNot(contains('游标原样续传')));

    expect(home, contains('记忆与人生'));
    expect(home, isNot(contains('个人记忆图谱')));

    expect(shell, contains("'今天'"));
    expect(shell, contains("'记忆'"));
    expect(shell, contains("'人生'"));
    expect(shell, contains("'家庭'"));
    expect(shell, contains("'我的'"));
    expect(shell, contains("label: const Text('记一下')"));
    expect(shell, isNot(contains("label: '时间轴'")));
    expect(shell, isNot(contains("label: '问记忆'")));
    expect(shell, isNot(contains("label: '记一下'")));
    expect(shell, isNot(contains('可信状态：\$certainty')));
    expect(shell, isNot(contains('识别意图：\$intent')));
    expect(shell, isNot(contains('retained Visit')));
    expect(shell, isNot(contains('S2-012')));
  });

  test('Flutter Product Experience V2 does not leak raw place or visit enums', () {
    final today = File('lib/today_footprint_page.dart').readAsStringSync();
    final place = File('lib/place_detail_page.dart').readAsStringSync();

    expect(today, isNot(contains('visit.visitSource')));
    expect(place, contains('_placeCategoryLabel(place.category)'));
    expect(place, isNot(contains("Text(_line('类型', place.category))")));
  });

  test('Flutter Product Experience V2 Today has the complete consumer hierarchy', () {
    final today = File('lib/today_footprint_page.dart').readAsStringSync();

    for (final section in [
      '今日足迹',
      '今日记忆',
      '快速记录',
      '家庭共享',
    ]) {
      expect(today, contains(section));
    }
    expect(today, contains('getTimelineEvents('));
    expect(today, contains('进入家庭后，只读取家人明确授权给你的内容。'));
    expect(today, isNot(contains('FamilyApi(widget.api).getFamily()')));
    expect(today, contains('MemoryDetailPage('));
  });

  test('Flutter Product Experience V2 production UI rejects developer language and raw enums', () {
    final files = _productionUiFiles();
    final visibleLiteralCount = files
        .map((file) => _visibleUiLiterals(file.readAsStringSync()).length)
        .fold<int>(0, (sum, count) => sum + count);

    // Fail closed if the scanner silently stops covering the production UI.
    expect(files.length, greaterThanOrEqualTo(10));
    expect(visibleLiteralCount, greaterThanOrEqualTo(50));

    final leaks = _productionLanguageLeaks();
    expect(
      leaks,
      isEmpty,
      reason: leaks.isEmpty
          ? null
          : 'Production-facing language leaks:\n${leaks.join('\n')}',
    );
  });

  test('Flutter Product Experience V2 memoir is story-first and hides implementation language', () {
    final memoir = File('lib/v2/memoirs_page.dart').readAsStringSync();

    expect(memoir, contains('这一年的照片'));
    expect(memoir, contains('这一年的时间线'));
    expect(memoir, contains('这一年的故事'));
    expect(memoir, contains('参考记录'));
    for (final forbidden in [
      'SEC-013',
      'timeline/photo',
      '确定性来源',
      'AI 生成面',
    ]) {
      expect(memoir, isNot(contains(forbidden)));
    }
  });

  test('Flutter Product Experience V2 family surface never exposes member ids', () {
    final page = File('lib/v2/family_page.dart').readAsStringSync();
    expect(page, contains("'家庭成员 \${index + 1}'"));
    expect(page, isNot(contains('shortFamilyMemberId')));
  });

  test('Flutter Product Experience V2 reuses shared loading error and offline states', () {
    final components = File('lib/ui/jiyi_components.dart').readAsStringSync();
    final shell = File('lib/stage1_app.dart').readAsStringSync();
    expect(components, contains('class JiYiLoadingState'));
    expect(components, contains('class JiYiErrorState'));
    expect(components, contains('class JiYiOfflineState'));
    expect(shell, contains('JiYiOfflineState(onRetry: _loadInitial)'));
    expect(shell, contains('getTimelineEvents(limit: 30)'));
    expect(shell, contains('TimelineReadPage.parse(raw)'));
    expect(shell, isNot(contains('late Future<List<Map<String, dynamic>>> _places')));
  });

  test('Flutter Product Experience V2 defines shared design token families', () {
    final tokens = File('lib/ui/jiyi_tokens.dart').readAsStringSync();
    final components = File('lib/ui/jiyi_components.dart').readAsStringSync();
    final theme = File('lib/ui/jiyi_theme.dart').readAsStringSync();

    for (final token in [
      'JiYiProductColors',
      'brandPrimary',
      'background',
      'surfaceElevated',
      'textPrimary',
      'aiAssisted',
      'family',
      'location',
      'media',
      'JiYiIconSize',
      'JiYiTapTarget',
      'JiYiMotion',
    ]) {
      expect(tokens, contains(token));
    }

    expect(components, contains('class JiYiHeroHeader'));
    expect(components, contains('class JiYiSectionHeader'));
    expect(components, contains('class JiYiActionCard'));
    expect(theme, contains('JiYiProductColors.brandPrimary'));
    expect(theme, contains('JiYiProductColors.background'));
    expect(theme, isNot(contains('0xFF446A57')));
    expect(theme, isNot(contains('0xFFF7F8F6')));
  });
}
