import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/photo_import_metadata.dart';
import 'package:jiyidashi/photo_import_page.dart';

class _Api extends JiYiApiClient {
  _Api() : super(baseUrl: 'https://gallery-ui.invalid/v1') {
    authenticatedUserId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
    accessToken = 'test';
  }
}

class _SelectedPicker extends PhotoImportPicker {
  _SelectedPicker(this.selection);

  final PhotoImportSelection selection;
  int calls = 0;

  @override
  Future<PhotoImportSelection> pick() async {
    calls++;
    return selection;
  }
}

SelectedPhotoImport _sample(PhotoCaptureEvidence evidence) => SelectedPhotoImport(
  path: '/selected/only/test.jpeg',
  originalFilename: 'test.jpeg',
  bytes: 100,
  contentType: 'image/jpeg',
  contentSha256: 'test-hash',
  evidence: evidence,
);

void main() {
  testWidgets('opening import page never invokes picker or uploads pictures', (tester) async {
    final picker = _SelectedPicker(
      const PhotoImportSelection(selected: [], failedNames: [], duplicates: 0),
    );
    await tester.pumpWidget(MaterialApp(
      home: PhotoImportPage(api: _Api(), picker: picker),
    ));
    await tester.pump();
    expect(picker.calls, 0);
    expect(find.textContaining('将上传所选原图'), findsOneWidget);
    expect(find.byKey(const ValueKey('photo-import-submit')), findsNothing);
  });

  testWidgets('selected source shows unknown capture time without inventing a visit', (tester) async {
    final picker = _SelectedPicker(
      PhotoImportSelection(
        selected: [_sample(const PhotoCaptureEvidence())],
        failedNames: const [],
        duplicates: 0,
      ),
    );
    await tester.pumpWidget(MaterialApp(home: PhotoImportPage(
      api: _Api(),
      picker: picker,
    )));
    await tester.tap(find.byKey(const ValueKey('photo-import-select')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(picker.calls, 1);
    expect(find.textContaining('拍摄时间未知'), findsOneWidget);
    expect(find.textContaining('地点未知'), findsOneWidget);
    expect(find.byKey(const ValueKey('photo-import-submit')), findsOneWidget);
  });
  testWidgets('account switch hides old gallery thumbnails and upload actions', (tester) async {
    final api = _Api();
    final picker = _SelectedPicker(PhotoImportSelection(
      selected: [_sample(const PhotoCaptureEvidence())],
      failedNames: const [],
      duplicates: 0,
    ));
    await tester.pumpWidget(MaterialApp(home: PhotoImportPage(
      api: api,
      picker: picker,
    )));
    await tester.tap(find.byKey(const ValueKey('photo-import-select')));
    await tester.pump();
    expect(find.text('test.jpeg'), findsOneWidget);
    api.authenticatedUserId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
    // The parent Shell rebuilds when authority changes; a plain API field
    // mutation alone does not notify Flutter's widget framework.
    await tester.pumpWidget(MaterialApp(home: PhotoImportPage(
      api: api,
      picker: picker,
    )));
    await tester.pump();
    expect(find.byKey(const ValueKey('photo-import-owner-changed')), findsOneWidget);
    expect(find.text('test.jpeg'), findsNothing);
    expect(find.byKey(const ValueKey('photo-import-submit')), findsNothing);
  });


}
