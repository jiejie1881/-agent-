"""Synthetic backup tests: no application, DB service, Docker, or model required."""

from contextlib import closing
import io
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import apply_same_day_candidate_update as update
from candidate_backup_validation import archive_entries, restore_archive, sqlite_fingerprint


def pack(items):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as tar:
        for name, content in items:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o600
            tar.addfile(info, io.BytesIO(content))
    return stream.getvalue()


class BackupWalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='backup-wal-test-', dir=update.ROOT / 'backend/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def snapshot(self, journal='wal'):
        source = self.root / 'source.sqlite3'
        with closing(sqlite3.connect(source)) as db:
            db.execute('PRAGMA journal_mode=' + journal)
            db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY,state TEXT,proof BLOB)')
            db.execute("INSERT INTO tasks VALUES(9,'COMPLETED',X'0102')")
            db.execute("INSERT INTO tasks VALUES(10,'PENDING',NULL)")
            db.commit()
            if journal == 'wal':
                self.assertGreater(Path(str(source) + '-wal').stat().st_size, 0)
            expected = sqlite_fingerprint(db)
            with closing(sqlite3.connect(':memory:')) as target:
                db.backup(target)
                return target.serialize(), expected

    def test_original_error_reproduced_only_by_deserialize(self):
        content, _ = self.snapshot()
        self.assertEqual(list(content[18:20]), [2, 2])
        with closing(sqlite3.connect(':memory:')) as db:
            db.deserialize(content)
            with self.assertRaisesRegex(sqlite3.OperationalError, 'unable to open database file'):
                db.execute('PRAGMA integrity_check').fetchall()

    def test_wal_file_restore_preserves_all_rows_and_headers(self):
        content, expected = self.snapshot()
        result = restore_archive(pack([('中文目录/checkpoints.sqlite3', content)]), self.root)
        row = result['entries']['中文目录/checkpoints.sqlite3']
        self.assertEqual(row['sqlite_tables'], expected)
        self.assertEqual(row['sqlite_header'], [2, 2])
        self.assertEqual(row['sqlite_integrity'], 'ok')
        self.assertTrue(result['temporary_copy_removed'])
        self.assertEqual(list(self.root.glob('restore-*')), [])

    def test_delete_mode_also_restores(self):
        content, expected = self.snapshot('delete')
        row = restore_archive(pack([('budget.sqlite3', content)]), self.root)['entries']['budget.sqlite3']
        self.assertEqual(row['sqlite_tables'], expected)
        self.assertEqual(row['sqlite_header'], [1, 1])

    def test_live_wal_commits_included_and_source_unchanged(self):
        source_dir = self.root / 'source'
        source_dir.mkdir()
        source = source_dir / 'checkpoints.sqlite3'
        with closing(sqlite3.connect(source)) as db:
            db.execute('PRAGMA journal_mode=wal')
            db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY,state TEXT)')
            db.execute("INSERT INTO tasks VALUES(9,'COMPLETED')")
            db.commit()
            expected = sqlite_fingerprint(db)
            before = {p.name: p.read_bytes() for p in source_dir.glob('*') if not p.name.endswith('-shm')}
            process = subprocess.run([sys.executable, '-B', '-c', update.VOLUME_SCRIPT, str(source_dir)],
                                     capture_output=True, timeout=20, check=True)
            self.assertEqual(before, {p.name: p.read_bytes() for p in source_dir.glob('*') if not p.name.endswith('-shm')})
            entries = archive_entries(process.stdout)
            self.assertEqual(set(entries), {'checkpoints.sqlite3'})
            restored = restore_archive(process.stdout, self.root)
            self.assertEqual(restored['entries']['checkpoints.sqlite3']['sqlite_tables'], expected)

    def test_corrupt_sqlite_fails_and_removes_copy(self):
        with self.assertRaises(sqlite3.DatabaseError):
            restore_archive(pack([('bad.sqlite3', b'SQLite format 3\x00' + b'broken' * 30)]), self.root)
        self.assertEqual(list(self.root.glob('restore-*')), [])

    def test_missing_wal_snapshot_detected_by_logical_comparison(self):
        source = self.root / 'source.sqlite3'
        with closing(sqlite3.connect(source)) as db:
            db.execute('PRAGMA journal_mode=wal')
            db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY,state TEXT)')
            db.commit()
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            db.execute("INSERT INTO tasks VALUES(9,'COMPLETED')")
            db.commit()
            expected = sqlite_fingerprint(db)
            # A naive main-file copy remains structurally valid but omits the
            # newly committed row in WAL. Row fingerprints must catch this.
            row = restore_archive(pack([('db.sqlite3', source.read_bytes())]), self.root)['entries']['db.sqlite3']
            self.assertEqual(row['sqlite_integrity'], 'ok')
            self.assertEqual(row['sqlite_tables']['tasks']['rows'], 0)
            self.assertEqual(expected['tasks']['rows'], 1)
            self.assertNotEqual(row['sqlite_tables'], expected)

    def test_empty_and_non_sqlite_archives_restore(self):
        self.assertEqual(restore_archive(pack([]), self.root)['entries'], {})
        result = restore_archive(pack([('回单 图片.png', b'synthetic-image')]), self.root)
        self.assertNotIn('sqlite_integrity', result['entries']['回单 图片.png'])

    def test_unsafe_paths_rejected_before_restore(self):
        for name in ['../escape', '/absolute', 'C:/windows', 'folder\\escape', 'a/../b']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                restore_archive(pack([(name, b'x')]), self.root)

    def test_duplicate_paths_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            archive_entries(pack([('same', b'first'), ('same', b'second')]))

    def test_symlinks_rejected(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as tar:
            info = tarfile.TarInfo('link')
            info.type = tarfile.SYMTYPE
            info.linkname = '/app/agent_data/checkpoints.sqlite3'
            tar.addfile(info)
        with self.assertRaisesRegex(ValueError, 'links'):
            archive_entries(stream.getvalue())

    def test_truncated_archive_rejected(self):
        data = pack([('proof', b'x' * 4096)])[:1024]
        with self.assertRaises(tarfile.ReadError):
            archive_entries(data)

    def test_manifest_requires_real_restore_results(self):
        data = pack([('proof', b'x')])
        result = update.archive_manifest(data, verifier=lambda value: restore_archive(value, self.root))
        self.assertEqual(result['proof']['size'], 1)
        with self.assertRaises(AssertionError):
            update.archive_manifest(data, verifier=lambda _: {'restore': 'FAIL', 'temporary_copy_removed': True})


if __name__ == '__main__':
    unittest.main(verbosity=2)
