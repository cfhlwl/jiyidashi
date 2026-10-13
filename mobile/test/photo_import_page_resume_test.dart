import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/api_client.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/photo_import_journal.dart';
import 'package:jiyidashi/photo_import_metadata.dart';
import 'package:jiyidashi/photo_import_page.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const ownerA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const ownerB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

class _Api extends JiYiApiClient {
  _Api(String owner) : super(baseUrl: 'https://photo-import-test.invalid/v1') {
    authenticatedUserId = owner;
    accessToken = 'test-token';
  }
}

void main() {
  sqfliteFfiInit();
  final factory = databaseFactoryFfiNoIsolate;

  testWidgets('reopen photos shows owner pending rows but never auto-uploads', (tester) async {
    final temp = await Directory.systemTemp.createTemp('jiyi-resume-ui-');
    final dbPath = '${temp.path}${Platform.pathSeparator}photo.sqlite';
    OfflineQueueStore createStore() => OfflineQueueStore(
      factory: factory,
      databasePathProvider: () async => dbPath,
    );
    final first = createStore();
    final source = File('${temp.path}${Platform.pathSeparator}select.jpeg');
    await source.writeAsBytes([0xff, 0xd8, 0xff, ...List<int>.filled(20, 0)]);
    final sha = sha256.convert(await source.readAsBytes()).toString();
    final journal = PhotoImportJournal(store: first, ownerUserId: ownerA);
    await journal.stage(
      SelectedPhotoImport(
        path: source.path,
        originalFilename: 'restored.jpeg',
        bytes: 23,
        contentType: 'image/jpeg',
        contentSha256: sha,
        evidence: const PhotoCaptureEvidence(),
      ),
      clientUploadId: 'c1c1c1c1-c1c1-41c1-81c1-c1c1c1c1c1c1',
    );
    await first.close();

    final reopened = createStore();
    await tester.pumpWidget(MaterialApp(home: PhotoImportPage(
      api: _Api(ownerA),
      offlineQueue: reopened,
    )));
    for (var i = 0; i < 60 &&
        find.textContaining('已恢复 1 张待续传照片').evaluate().isEmpty; i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(find.textContaining('已恢复 1 张待续传照片'), findsOneWidget);
    expect(find.text('restored.jpeg'), findsOneWidget);
    expect(find.byKey(const ValueKey('photo-import-submit')), findsOneWidget);
    expect((await journal.list()).single.status, OfflineQueueStatus.pending);
    await tester.pumpWidget(const MaterialApp(home: Scaffold()));
    await reopened.close();

    final b = createStore();
    await tester.pumpWidget(MaterialApp(home: PhotoImportPage(
      api: _Api(ownerB),
      offlineQueue: b,
    )));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('restored.jpeg'), findsNothing);
    expect(find.textContaining('已恢复 1 张待续传照片'), findsNothing);
    await tester.pumpWidget(const MaterialApp(home: Scaffold()));
    await b.close();
    await factory.deleteDatabase(dbPath);
    await temp.delete(recursive: true);
  });
}
