import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

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
    expect(today, contains('FamilyApi(widget.api).getFamily()'));
    expect(today, contains('MemoryDetailPage('));
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
