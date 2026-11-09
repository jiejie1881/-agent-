"""R0 synthetic-only unittest suite. Never loads pytest conftest or application."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

TOOL_PATH = Path('/opt/r0/tool.py') if Path('/opt/r0/tool.py').exists() else Path(__file__).resolve().parents[1] / 'tools/read_budget_ledger_forensics.py'
spec = importlib.util.spec_from_file_location('r0_forensics', TOOL_PATH)
r0 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r0)


class R0SyntheticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-', dir=os.environ['R0_EVIDENCE_ROOT'])
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.path = self.source / r0.LEDGER

    def tearDown(self):
        self.temp.cleanup()

    def make_db(self, *, wal=False):
        db = sqlite3.connect(self.path)
        if wal:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
        db.execute('CREATE TABLE gate(id INTEGER PRIMARY KEY,model TEXT NOT NULL,expires REAL NOT NULL,stopped INTEGER NOT NULL)')
        db.execute('CREATE TABLE calls(id INTEGER PRIMARY KEY AUTOINCREMENT,status TEXT NOT NULL,reserved INTEGER NOT NULL,sha TEXT NOT NULL,started REAL NOT NULL)')
        db.execute('INSERT INTO gate VALUES(1,?,?,0)', ('synthetic-only', 123456.0))
        db.execute("INSERT INTO calls(status,reserved,sha,started) VALUES('SUCCESS',1,'not-a-real-prompt',1)")
        db.commit()
        return db

    def copy(self):
        target = self.root / 'copy'
        result = r0.acquire_files(self.source, target, quiescence_proven=True)
        return target, result

    def test_01_noatime_preserves_deliberately_old_atime(self):
        self.path.write_bytes(b'only-synthetic-data')
        os.utime(self.path, ns=(1_000_000_000, 2_000_000_000))
        before = r0.metadata(self.path.stat())
        content, observed = r0.safe_read(self.path)
        self.assertEqual(content, b'only-synthetic-data')
        self.assertEqual(observed, before)
        self.assertEqual(r0.metadata(self.path.stat()), before)

    def test_02_permission_failure_has_no_fallback(self):
        calls = []
        def denied(path, flags):
            calls.append(flags)
            raise PermissionError(1, 'synthetic denial')
        with self.assertRaisesRegex(r0.GateBlocked, 'safe_open_failed'):
            r0.safe_read(self.path, opener=denied)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0] & os.O_NOATIME)
        self.assertFalse(calls[0] & os.O_CREAT)

    def test_03_missing_source_never_created(self):
        with self.assertRaises(r0.GateBlocked):
            r0.safe_read(self.path)
        self.assertFalse(self.path.exists())

    def test_04_symlink_rejected(self):
        original = self.root / 'other'
        original.write_bytes(b'untouched')
        self.path.symlink_to(original)
        with self.assertRaises(r0.GateBlocked):
            r0.safe_read(self.path)

    def test_05_hardlink_rejected(self):
        self.path.write_bytes(b'synthetic')
        os.link(self.path, self.root / 'hardlink')
        with self.assertRaisesRegex(r0.GateBlocked, 'single_link'):
            r0.safe_read(self.path)

    def test_06_size_limit_rejected(self):
        self.path.write_bytes(b'12345')
        with patch.object(r0, 'MAX_BYTES', 4), self.assertRaisesRegex(r0.GateBlocked, 'too_large'):
            r0.safe_read(self.path)

    def test_07_mutation_during_read_rejected(self):
        self.path.write_bytes(b'abcdef')
        first = True
        def mutate(fd, count):
            nonlocal first
            data = os.read(fd, count)
            if first:
                first = False
                with self.path.open('ab') as target:
                    target.write(b'changed')
            return data
        with self.assertRaisesRegex(r0.GateBlocked, 'metadata_changed'):
            r0.safe_read(self.path, reader=mutate)

    def test_08_quiescence_required_before_source_open(self):
        with patch.object(r0, 'strict_open', side_effect=AssertionError('must not open')):
            with self.assertRaisesRegex(r0.GateBlocked, 'quiescent_NOT_PROVEN'):
                r0.acquire_files(self.source, self.root / 'copy', quiescence_proven=False)
        self.assertFalse((self.root / 'copy').exists())

    def test_09_rollback_journal_rejected(self):
        db = self.make_db()
        db.close()
        (self.source / (r0.LEDGER + '-journal')).write_bytes(b'synthetic-hot-journal')
        with self.assertRaisesRegex(r0.GateBlocked, 'journal_present'):
            self.copy()

    def test_10_delete_snapshot_and_whitelist_queries(self):
        db = self.make_db()
        db.close()
        before = r0.metadata(self.path.stat())
        target, result = self.copy()
        rows = r0.inspect_copy(target / r0.LEDGER)
        self.assertEqual(len(result['files']), 1)
        self.assertEqual(r0.metadata(self.path.stat()), before)
        self.assertTrue(any(item['sql'] == 'PRAGMA integrity_check' and item['rows'] == [('ok',)] for item in rows))
        self.assertFalse(any('SELECT *' in item['sql'] for item in rows))

    def test_11_wal_commit_included_without_source_checkpoint(self):
        db = self.make_db(wal=True)
        try:
            wal = self.source / (r0.LEDGER + '-wal')
            self.assertGreater(wal.stat().st_size, 0)
            before = {p.name: r0.metadata(p.stat()) for p in self.source.iterdir()}
            target, result = self.copy()
            # Source directory listing above precedes the acquisition baseline.
            rows = r0.inspect_copy(target / r0.LEDGER)
            self.assertIn(r0.LEDGER + '-wal', result['files'])
            count = next(item['rows'] for item in rows if item['sql'] == 'SELECT status,COUNT(*) FROM calls GROUP BY status ORDER BY status')
            self.assertEqual(count, [('SUCCESS', 1)])
            self.assertEqual({p.name: r0.metadata(p.stat()) for p in self.source.iterdir()}, before)
        finally:
            db.close()

    def test_12_corrupt_private_copy_rejected(self):
        target = self.root / r0.LEDGER
        target.write_bytes(b'not a SQLite database')
        with self.assertRaises(sqlite3.DatabaseError):
            r0.inspect_copy(target)

    def test_13_SQL_source_path_outside_evidence_rejected(self):
        with patch.dict(os.environ, {'R0_EVIDENCE_ROOT': str(self.root / 'source')}):
            other = self.root / r0.LEDGER
            other.write_bytes(b'not opened')
            with self.assertRaisesRegex(r0.GateBlocked, 'not_approved_private_copy'):
                r0.inspect_copy(other)

    def test_14_evidence_output_never_overwritten(self):
        target = self.root / 'result.json'
        r0.save_new(target, {'synthetic': True})
        before = target.read_bytes()
        with self.assertRaises(FileExistsError):
            r0.save_new(target, {'synthetic': False})
        self.assertEqual(before, target.read_bytes())

    def test_15_evidence_path_escape_rejected(self):
        with self.assertRaisesRegex(r0.GateBlocked, 'outside_approved_root'):
            r0.safe_directory(self.root.parent, self.root)

    def test_16_destination_existing_rejected(self):
        db = self.make_db()
        db.close()
        (self.root / 'copy').mkdir()
        with self.assertRaises(FileExistsError):
            self.copy()

    def test_17_source_sidecar_symlink_rejected(self):
        db = self.make_db()
        db.close()
        (self.source / (r0.LEDGER + '-wal')).symlink_to(self.path)
        with self.assertRaisesRegex(r0.GateBlocked, 'link_or_special'):
            self.copy()

    def test_18_group_mutation_between_reads_rejected(self):
        db = self.make_db()
        db.close()
        original = r0.safe_read
        calls = 0
        def changed(path, **kwargs):
            nonlocal calls
            value = original(path, **kwargs)
            calls += 1
            if calls == 1:
                (self.source / (r0.LEDGER + '-wal')).write_bytes(b'appeared')
            return value
        with patch.object(r0, 'safe_read', changed), self.assertRaisesRegex(r0.GateBlocked, 'group_changed'):
            self.copy()

    def test_19_wrong_query_filename_rejected(self):
        target = self.root / 'another.sqlite3'
        target.write_bytes(b'not opened')
        with self.assertRaisesRegex(r0.GateBlocked, 'not_approved_private_copy'):
            r0.inspect_copy(target)

    def test_20_write_scope_device_open_is_denied(self):
        with self.assertRaises(PermissionError):
            fd = os.open('/dev/null', os.O_WRONLY)
            os.close(fd)

    def test_21_parent_escape_rejected_before_directory_creation(self):
        escape = self.root / 'missing' / '..' / '..' / 'must-not-exist'
        with self.assertRaisesRegex(r0.GateBlocked, 'outside_approved_root'):
            r0.safe_directory(escape, self.root, create=True)
        self.assertFalse((self.root.parent / 'must-not-exist').exists())

    def test_22_symlink_evidence_directory_rejected(self):
        real = self.root / 'real'
        real.mkdir()
        link = self.root / 'link'
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(r0.GateBlocked, 'symlink_or_reparse'):
            r0.safe_directory(link, self.root)

    def test_23_exact_desktop_drive_mapping_recognized(self):
        self.assertTrue(r0.bind_matches('C:/Users/example/evidence', '/run/desktop/mnt/host/c/Users/example/evidence'))
        self.assertTrue(r0.bind_matches('C:\\Users\\example\\tool.py', 'C:\\Users\\example\\tool.py'))

    def test_24_desktop_mapping_does_not_accept_sibling_or_escape(self):
        for actual in ('/run/desktop/mnt/host/d/Users/example/evidence',
                       '/run/desktop/mnt/host/c/Users/example/evidence-other',
                       '/run/desktop/mnt/host/c/Users/example/../evidence'):
            self.assertFalse(r0.bind_matches('C:/Users/example/evidence', actual))


if __name__ == '__main__':
    unittest.main()
