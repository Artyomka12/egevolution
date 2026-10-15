"""Explicit, offline migrations. Default: read-only audit. Never imports app/.env."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import time

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
MIN_SQLITE = (3, 26, 0)
LEDGER_SQL = """CREATE TABLE schema_migrations (
 version TEXT PRIMARY KEY NOT NULL, checksum TEXT NOT NULL,
 applied_at INTEGER NOT NULL, application_release TEXT NOT NULL)"""


class MigrationError(RuntimeError):
    pass


def connect(path, mode="ro"):
    db = sqlite3.connect(Path(path).resolve(strict=True).as_uri() + "?mode=" + mode,
                         uri=True, isolation_level=None, timeout=5)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA recursive_triggers=ON")
    return db


def statements(sql):
    pending = ""
    for character in sql:
        pending += character
        if character == ";" and sqlite3.complete_statement(pending):
            yield pending
            pending = ""
    if re.sub(r"--[^\n]*", "", pending).strip():
        raise MigrationError("Incomplete migration statement")


def files(directory):
    result = []
    numbers = set()
    for path in sorted(Path(directory).glob("*.sql")):
        match = re.fullmatch(r"(\d{3})_[a-z0-9_]+\.sql", path.name)
        if not match or match[1] in numbers:
            raise MigrationError("Invalid or duplicate migration number")
        numbers.add(match[1])
        raw = path.read_bytes()
        sql = raw.decode("utf-8")
        chunks = list(statements(sql))
        # Transaction boundaries/PRAGMAs cannot escape the runner's transaction.
        for chunk in chunks:
            clean = re.sub(r"--[^\n]*", "", chunk).strip()
            if path.name == '003_json_content.sql':
                # Audit only. Applying this replacement to an existing DB is
                # explicitly forbidden below; the separate builder creates a new DB.
                if not re.match(r'CREATE (?:TABLE|TRIGGER)\b', clean, re.I):
                    raise MigrationError('Unexpected JSON migration statement')
                continue
            if not re.match(r"(?:CREATE (?:TABLE|INDEX|UNIQUE INDEX|TRIGGER)\b|INSERT INTO (?:thematic_catalog_state|test_catalog_state)\b)", clean, re.I):
                raise MigrationError("Only additive DDL/catalog initialization is supported")
        result.append((path.name, hashlib.sha256(raw).hexdigest(), chunks))
    if not result:
        raise MigrationError("No migrations found")
    return result


def check_database(db):
    version = tuple(map(int, db.execute("SELECT sqlite_version()").fetchone()[0].split(".")))
    if version < MIN_SQLITE:
        raise MigrationError("SQLite 3.26.0 or newer is required")
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise MigrationError("Database integrity check failed")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise MigrationError("Foreign key violations; no automatic repairs")
    columns = db.execute("PRAGMA table_info(users)").fetchall()
    if not any(c[1] == "id" and c[2].upper() == "INTEGER" and c[5] == 1 for c in columns):
        raise MigrationError("Platform users(id INTEGER PRIMARY KEY) must already exist; app bootstrap is not run")


def pending_migrations(db, migrations):
    definitions = dict(db.execute("SELECT name,sql FROM sqlite_master"))
    objects = set(definitions)
    applied = list(db.execute("SELECT version,checksum FROM schema_migrations ORDER BY version")) if "schema_migrations" in objects else []
    known = [(name, checksum) for name, checksum, _ in migrations]
    if applied != known[:len(applied)]:
        raise MigrationError("Migration history/checksum mismatch; preserve applied files and reconcile baseline")
    pending = migrations[len(applied):]
    if any(name == '003_json_content.sql' for name, _ in applied):
        from scripts.json_content_migration import expected_schema
        expected = expected_schema(migrations)
        normalize = lambda sql: re.sub(r'\s+', ' ', sql.strip().rstrip(';')).strip()
        if any(key not in definitions or normalize(definitions[key] or '') != normalize(sql) for key,sql in expected.items()):
            raise MigrationError('Applied JSON schema differs from migration')
        return pending
    for name, _, chunks in migrations:
        if name == '003_json_content.sql':
            continue
        required = set()
        expected = {}
        for chunk in chunks:
            clean = re.sub(r"--[^\n]*", "", chunk).strip()
            match = re.search(r"CREATE (?:UNIQUE )?(?:TABLE|INDEX|TRIGGER)\s+(\w+)", clean, re.I)
            if match:
                required.add(match[1])
                expected[match[1]] = clean
        if any(name == row[0] for row in applied):
            if not required <= objects:
                raise MigrationError("Applied migration has missing schema objects")
            normalize = lambda sql: re.sub(r"\s+", " ", sql.strip().rstrip(";")).strip()
            if any(normalize(definitions[key] or "") != normalize(sql) for key, sql in expected.items()):
                raise MigrationError("Applied schema differs from the migration; manual review required")
        elif required & objects:
            raise MigrationError("Untracked/conflicting schema objects; baseline requires review")
    return pending


def fingerprint(db):
    h = hashlib.sha256()
    for line in db.iterdump():
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def migrate(database, *, apply=False, backup=None, offline=False, directory=MIGRATIONS):
    path = Path(database).resolve(strict=True)
    migrations = files(directory)
    # Stage 1.2 intentionally cannot write either live local database, even if
    # --apply is accidentally supplied. Enabling that is a separate approved step.
    if apply:
        for protected in (ROOT / "users.db", ROOT / ".local-data" / "dev-users.db",
                          ROOT / ".local-data" / "thematic-stage13.db"):
            if protected.exists() and path.samefile(protected):
                raise MigrationError("Live local databases are protected at stage 1.2")
    with closing(connect(path)) as db:
        db.execute("BEGIN")
        check_database(db)
        pending = pending_migrations(db, migrations)
        report = {"mode": "apply" if apply else "audit", "sqlite": sqlite3.sqlite_version,
                  "pending": [m[0] for m in pending], "applied": []}
        if not apply or not pending:
            return report
        if any(name == '003_json_content.sql' for name, _, _ in pending):
            raise MigrationError('JSON migration requires a separate verified candidate; in-place apply is disabled')
    if not offline or backup is None:
        raise MigrationError("Apply requires --confirm-offline and a verified --backup")
    backup_path = Path(backup).resolve(strict=True)
    if backup_path.samefile(path):
        raise MigrationError("Backup must be a separate file")
    if shutil.disk_usage(path.parent).free < max(path.stat().st_size * 2, 1024 * 1024):
        raise MigrationError("Insufficient free disk space")
    with closing(connect(backup_path)) as saved:
        saved.execute("BEGIN")
        check_database(saved)
        backup_hash = fingerprint(saved)
    with closing(connect(path, "rw")) as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            check_database(db)
            pending = pending_migrations(db, migrations)
            if not pending:
                db.rollback()
                return report
            if fingerprint(db) != backup_hash:
                raise MigrationError("Backup does not match the database under write lock")
            db.execute(LEDGER_SQL.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))
            for name, checksum, chunks in pending:
                for statement in chunks:
                    db.execute(statement)
                db.execute("INSERT INTO schema_migrations VALUES (?,?,?,?)",
                           (name, checksum, time.time_ns() // 1_000_000, "thematic-stage-1.2"))
                report["applied"].append(name)
            check_database(db)
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--confirm-offline", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.database, apply=args.apply, backup=args.backup,
                                 offline=args.confirm_offline), ensure_ascii=False))
    except (MigrationError, sqlite3.Error, OSError, ValueError) as error:
        # Do not print SQL values, student records, dumps or environment secrets.
        print(json.dumps({"error": type(error).__name__, "message": str(error)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
