from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import tempfile
from unittest import mock

from scripts.migrate import MigrationError, MIN_SQLITE, migrate as original_migrate, statements
from tests_support import DatabaseCase, ROOT, backup


def migrate(*args, **kwargs):
    """These tests retain coverage of the historical additive SQL migrations."""
    if "directory" in kwargs:
        return original_migrate(*args, **kwargs)
    with tempfile.TemporaryDirectory(prefix="ege-legacy-migrations-") as temporary:
        directory = Path(temporary)
        for name in ("001_thematic.sql", "002_tests.sql"):
            shutil.copyfile(ROOT / "migrations" / name, directory / name)
        return original_migrate(*args, directory=directory, **kwargs)


class MigrationTests(DatabaseCase):
    def apply(self):
        return migrate(self.path, apply=True, backup=self.backup_path, offline=True)

    def test_audit_readonly_apply_noop_and_platform_preserved(self):
        before = self.path.read_bytes()
        self.assertEqual(migrate(self.path)["pending"], ["001_thematic.sql", "002_tests.sql"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.apply()["applied"], ["001_thematic.sql", "002_tests.sql"])
        after = self.path.read_bytes()
        self.assertEqual(self.apply()["applied"], [])
        self.assertEqual(after, self.path.read_bytes())
        db = self.open()
        self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 3)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM user_results").fetchone()[0], 0)
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_add_tests_to_existing_thematic_chain(self):
        directory = self.root / "first"
        directory.mkdir()
        shutil.copyfile(ROOT / "migrations/001_thematic.sql", directory / "001_thematic.sql")
        migrate(self.path, apply=True, backup=self.backup_path, offline=True, directory=directory)
        db = self.open()
        db.execute("INSERT INTO thematic_variants(created_at,updated_at,created_by) VALUES(0,0,1)")
        before = [tuple(row) for row in db.execute("SELECT * FROM thematic_variants")]
        ledger = tuple(db.execute("SELECT * FROM schema_migrations").fetchone())
        backup(self.path, self.root / "thematic-backup.db")
        shutil.copyfile(ROOT / "migrations/002_tests.sql", directory / "002_tests.sql")
        result = migrate(self.path, apply=True, backup=self.root / "thematic-backup.db", offline=True, directory=directory)
        self.assertEqual(result["applied"], ["002_tests.sql"])
        self.assertEqual([tuple(row) for row in db.execute("SELECT * FROM thematic_variants")], before)
        self.assertEqual(tuple(db.execute("SELECT * FROM schema_migrations WHERE version='001_thematic.sql'").fetchone()), ledger)

    def test_backup_and_offline_required_and_match_under_lock(self):
        with self.assertRaises(MigrationError):
            migrate(self.path, apply=True)
        db = self.open()
        db.execute("UPDATE users SET username='synthetic-changed' WHERE id=2")
        with self.assertRaisesRegex(MigrationError, "Backup does not match"):
            self.apply()
        self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone())

    def test_protected_paths_and_hardlinks_fail_before_open(self):
        # Synthetic protected root exercises samefile without opening a live DB.
        fake_root = self.root / "project"
        (fake_root / ".local-data").mkdir(parents=True)
        for relative in ("users.db", ".local-data/dev-users.db", ".local-data/thematic-stage13.db"):
            target = fake_root / relative
            target.write_bytes(b"synthetic only")
            link = self.root / (target.name + ".hardlink")
            link.hardlink_to(target)
            for path in (target, link):
                with mock.patch("scripts.migrate.ROOT", fake_root), mock.patch(
                        "scripts.migrate.connect", side_effect=AssertionError("must not open protected database")):
                    with self.assertRaisesRegex(MigrationError, "protected"):
                        migrate(path, apply=True, backup=self.backup_path, offline=True)

    def test_late_failure_rolls_back_all_new_ddl_and_ledger(self):
        directory = self.root / "broken"
        directory.mkdir()
        for name in ("001_thematic.sql", "002_tests.sql"):
            shutil.copyfile(ROOT / "migrations" / name, directory / name)
        with (directory / "002_tests.sql").open("a", encoding="utf-8") as stream:
            stream.write("\nCREATE TABLE broken (id INTEGER,);\n")
        before = self.path.read_bytes()
        with self.assertRaises(sqlite3.OperationalError):
            migrate(self.path, apply=True, backup=self.backup_path, offline=True, directory=directory)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.open().execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations' OR name='tests'").fetchone())

    def test_checksum_unknown_history_and_trigger_drift_fail_closed(self):
        self.apply()
        directory = self.root / "changed"
        directory.mkdir()
        for name in ("001_thematic.sql", "002_tests.sql"):
            shutil.copyfile(ROOT / "migrations" / name, directory / name)
        with (directory / "002_tests.sql").open("a", encoding="utf-8") as stream:
            stream.write("\n-- altered checksum\n")
        with self.assertRaisesRegex(MigrationError, "history/checksum"):
            migrate(self.path, directory=directory)
        db = self.open()
        db.execute("DROP TRIGGER test_attempt_identity")
        db.execute("CREATE TRIGGER test_attempt_identity BEFORE UPDATE ON test_attempts BEGIN SELECT 1; END;")
        with self.assertRaisesRegex(MigrationError, "schema differs"):
            migrate(self.path)

    def test_transaction_escape_rejected_and_326_syntax_floor(self):
        self.assertEqual(MIN_SQLITE, (3, 26, 0))
        directory = self.root / "escape"
        directory.mkdir()
        (directory / "001_escape.sql").write_text("CREATE TABLE x(id INTEGER); COMMIT;", encoding="utf-8")
        with self.assertRaises(MigrationError):
            migrate(self.path, directory=directory)
        source = (ROOT / "migrations/002_tests.sql").read_text(encoding="utf-8")
        self.assertTrue(any("CREATE TRIGGER" in sql and "END;" in sql for sql in statements(source)))
        executable = "\n".join(line for line in source.splitlines() if not line.startswith("--")).upper()
        for forbidden in ("RETURNING ", " STRICT", "GENERATED ", "JSON_", "DROP COLUMN", "UPDATE FROM"):
            self.assertNotIn(forbidden, executable)
