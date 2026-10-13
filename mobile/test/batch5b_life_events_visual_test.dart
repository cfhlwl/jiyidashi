import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/ui/jiyi_theme.dart';
import 'package:jiyidashi/v2/life_editors.dart';
import 'package:jiyidashi/v2/life_event_detail_page.dart';
import 'package:jiyidashi/v2/life_events_page.dart';
import 'package:jiyidashi/v2/people_models.dart';

import 'v2_test_api.dart';

const bool _candidateMode = bool.fromEnvironment(
  'UIUX_V3_BATCH5B_CANDIDATE_MODE',
  defaultValue: false,
);
const _fixtureFontFamily = 'Batch 5B Noto Sans SC';

Future<void> _loadFixtureFonts() async {
  final cjkBytes = await File(
    'test/assets/visual/NotoSansSC-Regular.otf',
  ).readAsBytes();
  final cjk = FontLoader(_fixtureFontFamily)
    ..addFont(Future<ByteData>.value(ByteData.sublistView(cjkBytes)));
  await cjk.load();
  final iconBytes = await File(
    'test/fonts/MaterialIcons-Regular.otf',
  ).readAsBytes();
  final icons = FontLoader('MaterialIcons')
    ..addFont(Future<ByteData>.value(ByteData.sublistView(iconBytes)));
  await icons.load();
}

class _EmptyLifeEventsApi extends V2TestApi {
  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) {
    if (method == 'GET' && Uri.parse(path).path == '/life-events') {
      return Future<Object?>.value(const []);
    }
    return super.requestV2Json(method, path, body: body);
  }
}

class _OfflineLifeEventsApi extends V2TestApi {
  @override
  Future<Object?> requestV2Json(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) {
    if (method == 'GET' && Uri.parse(path).path == '/life-events') {
      return Future<Object?>.error(TransportException('网络连接失败'));
    }
    return super.requestV2Json(method, path, body: body);
  }
}

const _rootKey = ValueKey<String>('batch5b-visual-root');

Future<void> _pumpCandidate(
  WidgetTester tester,
  Widget child, {
  Size size = const Size(390, 844),
  double textScale = 1.0,
  ThemeData? theme,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      locale: const Locale('zh', 'CN'),
      theme: theme ?? JiYiTheme.light(fontFamily: _fixtureFontFamily),
      builder: (context, rendered) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(textScale)),
        child: rendered!,
      ),
      home: RepaintBoundary(key: _rootKey, child: child),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _expectCandidate(
  WidgetTester tester,
  String filename, {
  Finder? finder,
}) async {
  await expectLater(
    finder ?? find.byKey(_rootKey),
    matchesGoldenFile('goldens/$filename'),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(_loadFixtureFonts);

  testWidgets('candidate: Batch 5B Life Events production surface', (
    tester,
  ) async {
    if (!_candidateMode) return;
    await _pumpCandidate(tester, LifeEventsPage(api: V2TestApi()));
    await _expectCandidate(tester, 'life_events_v3_batch5b.png');
  });

  testWidgets('candidate: Batch 5B Life Event Detail production surface', (
    tester,
  ) async {
    if (!_candidateMode) return;
    await _pumpCandidate(
      tester,
      LifeEventDetailPage(api: V2TestApi(), eventId: v2EventId),
    );
    await _expectCandidate(tester, 'life_event_detail_v3_batch5b.png');
  });

  testWidgets('candidate: Batch 5B Life Event Editor production surface', (
    tester,
  ) async {
    if (!_candidateMode) return;
    await _pumpCandidate(
      tester,
      Builder(
        builder: (context) => Center(
          child: FilledButton(
            onPressed: () => showDialog<void>(
              context: context,
              builder: (_) =>
                  const LifeEventEditorDialog(places: <V2PlacePickerItem>[]),
            ),
            child: const Text('打开编辑器'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('打开编辑器'));
    await tester.pumpAndSettle();
    await _expectCandidate(
      tester,
      'life_event_editor_v3_batch5b.png',
      finder: find.byType(Overlay),
    );
  });

  testWidgets('candidate: Batch 5B Life Events dark surface', (tester) async {
    if (!_candidateMode) return;
    await _pumpCandidate(
      tester,
      LifeEventsPage(api: V2TestApi()),
      theme: JiYiTheme.dark(fontFamily: _fixtureFontFamily),
    );
    await _expectCandidate(tester, 'life_events_v3_batch5b_dark.png');
  });

  testWidgets('candidate: Batch 5B Life Events compact large text surface', (
    tester,
  ) async {
    if (!_candidateMode) return;
    await _pumpCandidate(
      tester,
      LifeEventDetailPage(api: V2TestApi(), eventId: v2EventId),
      size: const Size(320, 568),
      textScale: 2.0,
    );
    await _expectCandidate(tester, 'life_event_detail_v3_batch5b_compact.png');
  });

  testWidgets('candidate: Batch 5B Life Events empty state', (tester) async {
    if (!_candidateMode) return;
    await _pumpCandidate(tester, LifeEventsPage(api: _EmptyLifeEventsApi()));
    await _expectCandidate(tester, 'life_events_v3_batch5b_empty.png');
  });

  testWidgets('candidate: Batch 5B Life Events offline state', (tester) async {
    if (!_candidateMode) return;
    await _pumpCandidate(tester, LifeEventsPage(api: _OfflineLifeEventsApi()));
    await _expectCandidate(tester, 'life_events_v3_batch5b_offline.png');
  });
}
