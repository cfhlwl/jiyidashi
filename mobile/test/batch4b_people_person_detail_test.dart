import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:jiyidashi/v2/people_page.dart';
import 'package:jiyidashi/v2/person_detail_page.dart';

import 'v2_test_api.dart';

Future<void> _pumpBatch4b(WidgetTester tester, Widget child) async {
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: JiYiTheme.light(),
      home: child,
    ),
  );
}

class _NamedV2Api extends V2TestApi {
  _NamedV2Api(this.name, {this.owner = '00000000-0000-4000-8000-000000000002'}) {
    authenticatedUserId = owner;
  }

  final String name;
  final String owner;

  @override
  Map<String, dynamic> get person1 => {
        ...super.person1,
        'display_name': name,
        'user_id': owner,
      };

  @override
  Map<String, dynamic> get memory => {
        ...super.memory,
        'user_id': owner,
      };

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final route = Uri.parse(path).path;
    final value = await super.requestV2Json(method, path, body: body);
    if (method == 'GET' && route == '/people/interactions' && value is List) {
      return [
        for (final row in value.cast<Map<String, dynamic>>())
          {...row, 'person_display_name': name},
      ];
    }
    return value;
  }
}

class _DelayedPeopleApi extends V2TestApi {
  _DelayedPeopleApi(this.release);

  final Completer<void> release;

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    if (method == 'GET' && Uri.parse(path).path == '/people') {
      await release.future;
    }
    return super.requestV2Json(method, path, body: body);
  }
}

class _DelayedPersonApi extends V2TestApi {
  _DelayedPersonApi(this.release);

  final Completer<void> release;

  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final route = Uri.parse(path).path;
    if (method == 'GET' && route == '/people/$v2PersonId') {
      await release.future;
    }
    return super.requestV2Json(method, path, body: body);
  }
}

void main() {
  testWidgets('Batch 4B people renders truthful V2 data and accessible actions',
      (tester) async {
    final semantics = tester.ensureSemantics();
    try {
      await _pumpBatch4b(tester, PeoplePage(api: V2TestApi()));
      await tester.pumpAndSettle();

      expect(find.text('老张'), findsWidgets);
      expect(find.text('小李'), findsOneWidget);
      expect(find.text('最近相关的记忆'), findsOneWidget);
      expect(find.bySemanticsLabel('打开人物 老张'), findsOneWidget);
      expect(find.byKey(const ValueKey('people-add-person')), findsOneWidget);
    } finally {
      semantics.dispose();
    }
  });

  testWidgets('Batch 4B people rejects stale request after API/account rebind',
      (tester) async {
    final release = Completer<void>();
    final oldApi = _DelayedPeopleApi(release);
    await _pumpBatch4b(tester, PeoplePage(api: oldApi));
    await tester.pump();

    final newApi = _NamedV2Api('新账号的人物');
    await tester.pumpWidget(
      MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: JiYiTheme.light(),
        home: PeoplePage(api: newApi),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('新账号的人物'), findsOneWidget);

    release.complete();
    await tester.pumpAndSettle();
    expect(find.text('新账号的人物'), findsOneWidget);
    expect(find.text('老张'), findsNothing);
  });

  testWidgets('Batch 4B person detail preserves canonical data and actions',
      (tester) async {
    final semantics = tester.ensureSemantics();
    try {
      await _pumpBatch4b(
        tester,
        PersonDetailPage(api: V2TestApi(), personId: v2PersonId),
      );
      await tester.pumpAndSettle();

      expect(find.text('老张'), findsWidgets);
      expect(find.textContaining('至少 577 天'), findsOneWidget);
      expect(find.text('关于 TA 的记忆'), findsOneWidget);
      expect(find.text('团队记录'), findsOneWidget);
      expect(find.text('你们的关系'), findsOneWidget);
      expect(find.byKey(const ValueKey('person-edit')), findsOneWidget);
      expect(find.byKey(const ValueKey('person-link-memory')), findsOneWidget);
      expect(find.byKey(const ValueKey('person-open-graph')), findsOneWidget);
    } finally {
      semantics.dispose();
    }
  });

  testWidgets(
      'Batch 4B person detail rejects stale detail after API/account rebind',
      (tester) async {
    final release = Completer<void>();
    final oldApi = _DelayedPersonApi(release);
    await _pumpBatch4b(
      tester,
      PersonDetailPage(api: oldApi, personId: v2PersonId),
    );
    await tester.pump();

    final newApi = _NamedV2Api('新账号的人物详情');
    await tester.pumpWidget(
      MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: JiYiTheme.light(),
        home: PersonDetailPage(api: newApi, personId: v2PersonId),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('新账号的人物详情'), findsOneWidget);

    release.complete();
    await tester.pumpAndSettle();
    expect(find.text('新账号的人物详情'), findsOneWidget);
    expect(find.text('老张'), findsNothing);
  });

  testWidgets('Batch 4B people and detail fit compact and large text layouts',
      (tester) async {
    tester.view.physicalSize = const Size(320, 568);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    await _pumpBatch4b(tester, PeoplePage(api: V2TestApi()));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);

    await tester.pumpWidget(
      MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: JiYiTheme.light(),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(
            textScaler: const TextScaler.linear(2),
          ),
          child: child!,
        ),
        home: PersonDetailPage(api: V2TestApi(), personId: v2PersonId),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('关于 TA 的记忆'), findsOneWidget);
    expect(find.byKey(const ValueKey('person-edit')), findsOneWidget);
  });
}
