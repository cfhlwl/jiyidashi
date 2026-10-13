import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jiyidashi/offline_queue.dart';
import 'package:jiyidashi/photo_import_journal.dart';
import 'package:jiyidashi/photo_import_metadata.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

const ownerA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const ownerB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const uploadId = '12345678-1234-4234-8234-123456789abc';

void main() {
  sqfliteFfiInit();
  final factory = databaseFactoryFfiNoIsolate;
  late Directory temp;
  late String databasePath;
  late File pickerFile;
  late String digest;

  OfflineQueueStore createStore() => OfflineQueueStore(
    factory: factory, databasePathProvider: () async => databasePath,
  );

  setUp(() async {
    temp = await Directory.systemTemp.createTemp('jiyi-import-journal-');
    databasePath = '${temp.path}${Platform.pathSeparator}outbox.sqlite3';
    pickerFile = File('${temp.path}${Platform.pathSeparator}picked.jpeg');
    await pickerFile.writeAsBytes([0xff, 0xd8, 0xff, ...List.filled(40, 0)]);
    digest = sha256.convert(await pickerFile.readAsBytes()).toString();
  });

  tearDown(() async {
    await factory.deleteDatabase(databasePath);
    if (await temp.exists()) await temp.delete(recursive: true);
  });

  SelectedPhotoImport selected() => SelectedPhotoImport(
    path: pickerFile.path,
    originalFilename: 'source.jpeg',
    bytes: 43,
    contentType: 'image/jpeg',
    contentSha256: digest,
    evidence: PhotoCaptureEvidence(
      localCaptureTime: '2025-08-09 01:15:00',
      captureTimeUtc: DateTime.utc(2025, 8, 8, 17, 15),
      utcOffsetMinutes: 480,
    ),
  );

  test('outbox copy and client UUID survive process reopening without auto-upload', () async {
    final first = createStore();
    final journal = PhotoImportJournal(store: first, ownerUserId: ownerA);
    final row = await journal.stage(selected(), clientUploadId: uploadId);
    expect(row.status, OfflineQueueStatus.pending);
    expect(row.operationType, OfflineQueueStore.photoImportOperation);
    expect(await first.listDeliverable(ownerA), isEmpty);
    final staged = await journal.selectedFrom(row);
    expect(staged.path, isNot(pickerFile.path));
    expect(await File(staged.path).readAsBytes(), await pickerFile.readAsBytes());
    await first.close();

    final reopened = createStore();
    final again = PhotoImportJournal(store: reopened, ownerUserId: ownerA);
    final rows = await again.list();
    expect(rows, hasLength(1));
    expect(rows.single.clientUuid, uploadId);
    final recovered = await again.selectedFrom(rows.single);
    expect(recovered.evidence.captureTimeUtc, DateTime.utc(2025, 8, 8, 17, 15));
    expect(await reopened.listDeliverable(ownerA), isEmpty);
    final sending = await again.begin(rows.single);
    expect(sending.status, OfflineQueueStatus.sending);
    await reopened.close();

    final afterCrash = createStore();
    final crashJournal = PhotoImportJournal(store: afterCrash, ownerUserId: ownerA);
    final uncertain = (await crashJournal.list()).single;
    expect(uncertain.status, OfflineQueueStatus.failed);
    final resumed = await crashJournal.begin(uncertain);
    expect(resumed.clientUuid, uploadId);
    expect(resumed.attemptCount, 2);
    final committed = await crashJournal.complete(resumed, memoryId: 'server-memory');
    expect(committed.serverResourceId, 'server-memory');
    expect(committed.status, OfflineQueueStatus.completed);
    expect(await File(staged.path).exists(), false);
    expect(await afterCrash.listDeliverable(ownerA), isEmpty);
    await afterCrash.close();
  });

  test('account deletion clears both record and owned staged bytes', () async {
    final store = createStore();
    final journal = PhotoImportJournal(store: store, ownerUserId: ownerA);
    final row = await journal.stage(selected(), clientUploadId: uploadId);
    final staged = await journal.selectedFrom(row);
    final other = PhotoImportJournal(store: store, ownerUserId: ownerB);
    final b = await other.stage(
      selected(), clientUploadId: '77777777-7777-4777-8777-777777777777',
    );
    final otherPath = (await other.selectedFrom(b)).path;
    await store.quiesceForAccountDeletion(ownerA);
    await store.purgeOwner(ownerA);
    expect(await File(staged.path).exists(), false);
    expect(await journal.list(), isEmpty);
    expect(await File(otherPath).exists(), true);
    expect((await other.list()).single.ownerUserId, ownerB);
    await store.close();
  });

  test('staging rejects changed selection bytes without queue record', () async {
    final store = createStore();
    final journal = PhotoImportJournal(store: store, ownerUserId: ownerA);
    final first = selected();
    await pickerFile.writeAsBytes([0xff, 0xd8, 0xff, ...List.filled(41, 0)]);
    await expectLater(journal.stage(first, clientUploadId: uploadId),
        throwsA(isA<FormatException>()));
    expect(await journal.list(), isEmpty);
    final dir = await store.photoImportOwnerDirectory(ownerA);
    if (await dir.exists()) expect(await dir.list().toList(), isEmpty);
    await store.close();
  });

  test('journal refuses payload from other owner', () async {
    final store = createStore();
    final source = PhotoImportJournal(store: store, ownerUserId: ownerA);
    final row = await source.stage(selected(), clientUploadId: uploadId);
    final wrong = PhotoImportJournal(store: store, ownerUserId: ownerB);
    await expectLater(wrong.selectedFrom(row), throwsA(isA<StateError>()));
    expect(await wrong.list(), isEmpty);
    await store.close();
  });
}
