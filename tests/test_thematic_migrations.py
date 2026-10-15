from contextlib import closing
import hashlib
from pathlib import Path
import shutil
import sqlite3
from unittest import mock
from thematic_support import DatabaseCase, ROOT, backup
from scripts.migrate import migrate, MigrationError, statements, MIN_SQLITE


class MigrationTests(DatabaseCase):
    def legacy_directory(self):
        directory = self.root / 'legacy-migrations'
        directory.mkdir(exist_ok=True)
        for name in ('001_thematic.sql', '002_tests.sql'):
            shutil.copyfile(ROOT / 'migrations' / name, directory / name)
        return directory

    def apply(self):
        # Existing-schema installer remains tested on synthetic SQLite only.
        # JSON conversion creates a separate candidate, never replaces a DB.
        return migrate(self.path, apply=True, backup=self.backup_path, offline=True,
                       directory=self.legacy_directory())

    def test_audit_read_only_and_apply_idempotent(self):
        before = self.path.read_bytes()
        self.assertEqual(migrate(self.path)['pending'], ['001_thematic.sql', '002_tests.sql', '003_json_content.sql'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.apply()['applied'], ['001_thematic.sql', '002_tests.sql'])
        after = self.path.read_bytes()
        self.assertEqual(self.apply()['applied'], [])
        self.assertEqual(after, self.path.read_bytes())
        db = self.open()
        self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM user_results').fetchone()[0], 0)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM thematic_variants').fetchone()[0], 0)
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_json_candidate_audit_preserves_source(self):
        import tempfile
        from scripts.json_content_migration import build_candidate
        self.apply()
        before = self.path.read_bytes()
        with tempfile.TemporaryDirectory(prefix='ege-json-migration-audit-') as folder:
            target = Path(folder) / 'candidate'
            report = build_candidate(self.path, target)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(report['integrity_check'], 'ok')
            self.assertEqual(report['foreign_key_check'], [])
            candidate = target / 'users.db'
            saved = candidate.read_bytes()
            self.assertEqual(migrate(candidate)['pending'], [])
            self.assertEqual(candidate.read_bytes(), saved)

    def test_missing_users_is_explicit_precondition_not_bootstrap(self):
        path = self.root / 'empty.db'
        with closing(sqlite3.connect(path)):
            pass
        before = path.read_bytes()
        with self.assertRaisesRegex(MigrationError, 'users'):
            migrate(path)
        self.assertEqual(path.read_bytes(), before)

    def test_apply_requires_matching_backup_and_offline(self):
        with self.assertRaises(MigrationError):
            migrate(self.path, apply=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE users SET username='changed'")
            db.commit()
        with self.assertRaisesRegex(MigrationError, 'Backup does not match'):
            self.apply()
        self.assertFalse(self.open().execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone())

    def test_live_databases_rejected_before_connect(self):
        for path in (ROOT / 'users.db', ROOT / '.local-data/dev-users.db'):
            if path.exists():
                with mock.patch('scripts.migrate.connect', side_effect=AssertionError('Must not open live DB')):
                    with self.assertRaisesRegex(MigrationError, 'protected'):
                        migrate(path, apply=True, backup=self.backup_path, offline=True)

    def test_late_sql_failure_rolls_back_ddl_and_ledger(self):
        directory = self.root / 'migrations'
        directory.mkdir()
        source = (ROOT / 'migrations/001_thematic.sql').read_text()
        (directory / '001_thematic.sql').write_text(source + '\nCREATE TABLE broken (id INTEGER,);\n')
        before = self.path.read_bytes()
        with self.assertRaises(sqlite3.OperationalError):
            migrate(self.path, apply=True, backup=self.backup_path, offline=True, directory=directory)
        db = self.open()
        self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'thematic_%' OR name='schema_migrations'").fetchone())
        self.assertEqual(self.path.read_bytes(), before)

    def test_checksum_and_unknown_history_fail_closed(self):
        self.apply()
        directory = self.root / 'migrations'
        shutil.copytree(ROOT / 'migrations', directory)
        with (directory / '001_thematic.sql').open('a') as f:
            f.write('\n-- changed\n')
        with self.assertRaisesRegex(MigrationError, 'history/checksum'):
            migrate(self.path, directory=directory)
        db = self.open()
        db.execute("UPDATE schema_migrations SET version='001_tests.sql' WHERE version='001_thematic.sql'")
        with self.assertRaises(MigrationError):
            migrate(self.path)

    def test_schema_collision_and_legacy_orphans(self):
        db = self.open()
        db.execute('CREATE TABLE thematic_variants (id INTEGER PRIMARY KEY)')
        with self.assertRaisesRegex(MigrationError, 'conflicting'):
            migrate(self.path)
        db.execute('DROP TABLE thematic_variants')
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('INSERT INTO user_results(user_id) VALUES (999)')
        with self.assertRaisesRegex(MigrationError, 'Foreign key'):
            migrate(self.path)

    def test_modified_applied_trigger_is_detected(self):
        self.apply()
        db=self.open()
        db.execute('DROP TRIGGER thematic_item_update')
        db.execute("CREATE TRIGGER thematic_item_update BEFORE UPDATE ON thematic_version_items BEGIN SELECT 1; END;")
        with self.assertRaisesRegex(MigrationError, 'schema differs'):
            migrate(self.path)

    def test_transaction_escape_rejected_and_sqlite_floor(self):
        self.assertEqual(MIN_SQLITE, (3,26,0))
        directory = self.root / 'bad'
        directory.mkdir()
        (directory / '001_bad.sql').write_text('CREATE TABLE x(id INTEGER); COMMIT;')
        with self.assertRaises(MigrationError):
            migrate(self.path, directory=directory)
        source = (ROOT / 'migrations/001_thematic.sql').read_text()
        chunks = list(statements(source))
        self.assertTrue(any('CREATE TRIGGER' in chunk and 'END;' in chunk for chunk in chunks))
        # No dependency on JSON1 or SQL additions newer than the target runtime.
        executable = '\n'.join(line for line in source.splitlines() if not line.startswith('--')).upper()
        for forbidden in ('RETURNING ', ' STRICT', 'GENERATED ', 'JSON_', 'DROP COLUMN', 'UPDATE FROM'):
            self.assertNotIn(forbidden, executable)
