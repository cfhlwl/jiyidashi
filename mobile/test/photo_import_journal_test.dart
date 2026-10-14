import 'dart:async';
import 'dart:convert';
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

class _PausedReservationStore extends OfflineQueueStore {
  _PausedReservationStore(String path)
      : super(
          factory: databaseFactoryFfiNoIsolate,
          databasePathProvider: () async => path,
        );

  final Completer<void> entered = Completer<void>();
  final Completer<void> proceed = Completer<void>();

  @override
  Future<OfflineQueueItem> reservePhotoImport({
    required String ownerUserId,
    required String clientUuid,
    required String sha256Hex,
    required Map<String, dynamic> payload,
  }) async {
    entered.complete();
    await proceed.future;
    return super.reservePhotoImport(
      ownerUserId: ownerUserId,
      clientUuid: clientUuid,
      sha256Hex: sha256Hex,
      payload: payload,
    );
  }
}

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
    if (await temp.exists()) {
      await temp.delete(recursive: true);
    }
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

  test('v4 -> v5 migrates legacy same-owner duplicate rows without erasing work', () async {
    final legacy = await factory.openDatabase(
      databasePath,
      options: OpenDatabaseOptions(
        version: 4,
        onCreate: (db, _) async {
          await db.execute('''
            CREATE TABLE offline_queue (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              owner_user_id TEXT NOT NULL,
              client_uuid TEXT NOT NULL,
              operation_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              status TEXT NOT NULL,
              attempt_count INTEGER NOT NULL DEFAULT 0,
              last_error TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              completed_at TEXT,
              cancelled_at TEXT,
              retryable INTEGER NOT NULL DEFAULT 1,
              server_resource_id TEXT,
              UNIQUE(owner_user_id, client_uuid)
            )
          ''');
        },
      ),
    );
    final timestamp = DateTime.utc(2025, 9, 1).toIso8601String();
    Future<void> legacyRow(String owner, String uuid, String status) async {
      await legacy.insert('offline_queue', {
        'owner_user_id': owner,
        'client_uuid': uuid,
        'operation_type': OfflineQueueStore.photoImportOperation,
        'payload_json': jsonEncode({
          'staged_path': '/fixture/$owner/$uuid.bin',
          'original_filename': 'legacy.jpeg',
          'size_bytes': 43,
          'content_type': 'image/jpeg',
          'sha256': digest,
          'evidence': <String, dynamic>{},
        }),
        'status': status,
        'created_at': timestamp,
        'updated_at': timestamp,
      });
    }
    const secondUuid = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
    await legacyRow(ownerA, uploadId, 'pending');
    await legacyRow(ownerA, secondUuid, 'sending');
    await legacyRow(ownerB, 'ffffffff-ffff-4fff-8fff-ffffffffffff', 'pending');
    await legacy.close();

    final upgraded = createStore();
    final allA = await upgraded.listAll(ownerA);
    expect(allA, hasLength(2), reason: 'do not erase duplicate old attempts');
    expect(allA.singleWhere((r) => r.clientUuid == secondUuid).status,
        OfflineQueueStatus.failed, reason: 'interrupted sending is recovered');
    final winner = await upgraded.findClaimedPhoto(ownerA, digest);
    expect(winner?.clientUuid, uploadId);
    expect((await upgraded.findClaimedPhoto(ownerB, digest))?.ownerUserId, ownerB);
    await upgraded.close();
  });

  test('orphan sweep cannot erase an active source staged before SQLite receipt', () async {
    final store = _PausedReservationStore(databasePath);
    final journal = PhotoImportJournal(store: store, ownerUserId: ownerA);
    final staging = journal.stage(selected(), clientUploadId: uploadId);
    await store.entered.future;
    // Deliberately no grace interval. Inter-process owner lock, not a
    // timestamp heuristic, must prevent deletion before row commit.
    var sweepCompleted = false;
    final sweep = journal.sweepOrphanedFiles(
      const <OfflineQueueItem>[],
      gracePeriod: Duration.zero,
      now: DateTime.now().add(const Duration(minutes: 2)),
    ).then((count) {
      sweepCompleted = true;
      return count;
    });
    await Future<void>.delayed(const Duration(milliseconds: 40));
    expect(sweepCompleted, false, reason: 'source copy owns exclusive lock');
    store.proceed.complete();
    final row = await staging;
    expect(row.status, OfflineQueueStatus.pending);
    expect(await sweep, 0);
    final staged = await journal.selectedFrom(row);
    expect(await File(staged.path).exists(), true);
    expect(await store.listAll(ownerA), hasLength(1));
    await store.close();
  });

  test('account deletion waits for source copy before purge', () async {
    final store = _PausedReservationStore(databasePath);
    final journal = PhotoImportJournal(store: store, ownerUserId: ownerA);
    final staging = journal.stage(selected(), clientUploadId: uploadId);
    await store.entered.future;
    var quiesced = false;
    final barrier = store.quiesceForAccountDeletion(ownerA).then((_) {
      quiesced = true;
    });
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(quiesced, false, reason: 'never purge while copied image is in flight');
    store.proceed.complete();
    await expectLater(staging, throwsA(isA<StateError>()));
    await barrier;
    expect(quiesced, true);
    await store.purgeOwner(ownerA);
    expect(await store.listAll(ownerA), isEmpty);
    final folder = await store.photoImportOwnerDirectory(ownerA);
    expect(await folder.exists(), false);
    await store.close();
  });

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

  test('same-session retry rejects same-length tampering of staged bytes', () async {
    final store = createStore();
    final journal = PhotoImportJournal(store: store, ownerUserId: ownerA);
    final first = await journal.stage(selected(), clientUploadId: uploadId);
    final sending = await journal.begin(first);
    final failed = await journal.failed(sending);
    final staged = await journal.selectedFrom(failed);
    final bytes = await File(staged.path).readAsBytes();
    bytes[bytes.length - 1] ^= 1;
    await File(staged.path).writeAsBytes(bytes, flush: true);
    expect(await File(staged.path).length(), selected().bytes);
    // The original picker copy is intact, but the *uploaded* copy is not.
    expect(await pickerFile.readAsBytes(), isNot(bytes));
    await expectLater(
      journal.stage(selected(), clientUploadId: uploadId),
      throwsA(isA<FormatException>()),
    );
    await expectLater(journal.verifyStaged(failed),
        throwsA(isA<FormatException>()));
    expect((await store.findByClientUuid(ownerA, uploadId))?.status,
        OfflineQueueStatus.failed);
    await store.close();
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
    if (await dir.exists()) {
      final all = await dir.list().toList();
      expect(
        all.where((entry) =>
            entry.path.endsWith('.bin') ||
            entry.path.endsWith('.bin.partial')),
        isEmpty,
        reason: 'private lock metadata is allowed; orphan photo bytes are not',
      );
    }
    await store.close();
  });

  test('withdraw unsubmitted file cancels queue and deletes only staged copy', () async {
    final store = createStore();
    final journal = PhotoImportJournal(store: store, ownerUserId: ownerA);
    final item = await journal.stage(selected(), clientUploadId: uploadId);
    final staged = await journal.selectedFrom(item);
    await journal.withdraw(item);
    final row = (await journal.list()).single;
    expect(row.status, OfflineQueueStatus.cancelled);
    expect(await File(staged.path).exists(), false);
    expect(await pickerFile.exists(), true, reason: 'never delete user gallery source');
    expect(await journal.findSameContent(digest), isNull);
    expect(await store.listDeliverable(ownerA), isEmpty);
    await store.close();
  });

  test('completed SHA is reused only within original owner', () async {
    final store = createStore();
    final a = PhotoImportJournal(store: store, ownerUserId: ownerA);
    final b = PhotoImportJournal(store: store, ownerUserId: ownerB);
    final pending = await a.stage(selected(), clientUploadId: uploadId);
    expect((await a.findSameContent(digest))?.clientUuid, uploadId);
    expect(await b.findSameContent(digest), isNull);
    final inFlight = await a.begin(pending);
    await a.complete(inFlight, memoryId: 'existing-memory-id');
    final match = await a.findSameContent(digest);
    expect(match?.status, OfflineQueueStatus.completed);
    expect(match?.serverResourceId, 'existing-memory-id');
    expect(await b.findSameContent(digest), isNull);
    await store.close();
  });

  test('symlinked private photo-import parent cannot redirect selected originals',
      () async {
    if (Platform.isWindows) {
      return; // Unprivileged Windows links can be disabled.
    }
    final store = createStore();
    final journal = PhotoImportJournal(store: store, ownerUserId: ownerA);
    final dir = await store.photoImportOwnerDirectory(ownerA);
    final outside = Directory('${temp.path}${Platform.pathSeparator}outside');
    await outside.create();
    await Link(dir.parent.path).create(outside.path);
    await expectLater(
      journal.stage(selected(), clientUploadId: uploadId),
      throwsA(isA<FormatException>()),
    );
    expect(await outside.list().toList(), isEmpty);
    expect(await journal.findSameContent(digest), isNull);
    await store.close();
  });

  test('orphan staged copy with same path but altered bytes never becomes an upload', () async {
    final store = createStore();
    final journal = PhotoImportJournal(store: store, ownerUserId: ownerA);
    final dir = await store.photoImportOwnerDirectory(ownerA);
    await dir.create(recursive: true);
    final orphan = File('${dir.path}${Platform.pathSeparator}$uploadId.bin');
    await orphan.writeAsBytes([0xff, 0xd8, 0xff, ...List.filled(40, 9)]);
    await expectLater(journal.stage(selected(), clientUploadId: uploadId),
        throwsA(isA<FormatException>()));
    expect(await journal.list(), isEmpty);
    expect(await orphan.exists(), false);
    await store.close();
  });

  test('parallel same-owner SHA is reserved by only one SQLite transaction', () async {
    final storeA = createStore();
    final storeB = createStore();
    final a = PhotoImportJournal(store: storeA, ownerUserId: ownerA);
    final b = PhotoImportJournal(store: storeB, ownerUserId: ownerA);
    final secondUuid = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
    final results = await Future.wait([
      a.stage(selected(), clientUploadId: uploadId),
      b.stage(selected(), clientUploadId: secondUuid),
    ]);
    expect(results.map((r) => r.clientUuid).toSet(), hasLength(1));
    final claimed = (await a.findSameContent(digest))!;
    expect(claimed.clientUuid, results.first.clientUuid);
    expect((await a.list()).where((r) => r.status != OfflineQueueStatus.cancelled),
        hasLength(1));
    final loser = results.first.clientUuid == uploadId ? secondUuid : uploadId;
    final dir = await storeA.photoImportOwnerDirectory(ownerA);
    expect(await File('${dir.path}${Platform.pathSeparator}$loser.bin').exists(),
        false);
    final other = PhotoImportJournal(store: storeA, ownerUserId: ownerB);
    final ownB = await other.stage(
      selected(), clientUploadId: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
    );
    expect(ownB.ownerUserId, ownerB);
    expect((await other.findSameContent(digest))!.clientUuid, ownB.clientUuid);
    await storeA.close();
    await storeB.close();
  });

  test('orphan sweep removes only old unreferenced regular UUID files', () async {
    final store = createStore();
    final journal = PhotoImportJournal(store: store, ownerUserId: ownerA);
    final row = await journal.stage(selected(), clientUploadId: uploadId);
    final dir = await store.photoImportOwnerDirectory(ownerA);
    final valid = File((await journal.selectedFrom(row)).path);
    final orphanUuid = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
    final oldPart = File('${dir.path}${Platform.pathSeparator}$orphanUuid.bin.partial');
    final oldBin = File('${dir.path}${Platform.pathSeparator}$orphanUuid.bin');
    final recent = File('${dir.path}${Platform.pathSeparator}cccccccc-cccc-4ccc-8ccc-cccccccccccc.bin.partial');
    await oldPart.writeAsBytes([1]);
    await oldBin.writeAsBytes([2]);
    await recent.writeAsBytes([3]);
    final old = DateTime.now().subtract(const Duration(hours: 3));
    await oldPart.setLastModified(old);
    await oldBin.setLastModified(old);
    await valid.setLastModified(old);
    final b = PhotoImportJournal(store: store, ownerUserId: ownerB);
    final other = await b.stage(
      selected(), clientUploadId: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
    );
    final otherFile = File((await b.selectedFrom(other)).path);
    await otherFile.setLastModified(old);

    expect(await journal.sweepOrphanedFiles(await store.listAll(ownerA)), 2);
    expect(await oldPart.exists(), false);
    expect(await oldBin.exists(), false);
    expect(await recent.exists(), true);
    expect(await valid.exists(), true, reason: 'never delete referenced pending');
    expect(await otherFile.exists(), true, reason: 'never cross owner');
    await journal.withdraw(row);
    expect(await valid.exists(), false);
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
