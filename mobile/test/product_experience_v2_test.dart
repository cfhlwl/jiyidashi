import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Flutter Product Experience V2 uses human-facing People and Life language', () {
    final people = File('lib/v2/people_page.dart').readAsStringSync();
    final life = File('lib/v2/life_page.dart').readAsStringSync();
    final home = File('lib/v2/v2_home_page.dart').readAsStringSync();

    expect(people, contains('重要的人'));
    expect(people, contains('最近相关的记忆'));
    expect(people, isNot(contains('Person ↔ Memory')));
    expect(people, isNot(contains('row.link.relationKind')));

    expect(life, contains('我的人生'));
    expect(life, contains('人生经历'));
    expect(life, contains('人生故事'));
    expect(life, isNot(contains('CRUD')));
    expect(life, isNot(contains('LifeEvent')));
    expect(life, isNot(contains('Memory 证据')));
    expect(life, isNot(contains('服务端确定性投影')));
    expect(life, isNot(contains('游标原样续传')));

    expect(home, contains('记忆与人生'));
    expect(home, isNot(contains('个人记忆图谱')));
  });

  test('Flutter Product Experience V2 defines shared design token families', () {
    final tokens = File('lib/ui/jiyi_tokens.dart').readAsStringSync();
    final components = File('lib/ui/jiyi_components.dart').readAsStringSync();

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
  });
}
