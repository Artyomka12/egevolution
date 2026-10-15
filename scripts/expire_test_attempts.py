"""Explicit local tests deadline worker. Does not import app or read .env."""
import argparse
from contextlib import closing
import math
from pathlib import Path
import sys
import sqlite3
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.tests import repository, service


def checked_database(path):
    target = Path(path).expanduser().resolve(strict=True)
    protected = (ROOT / "users.db", ROOT / ".local-data" / "dev-users.db",
                 ROOT / ".local-data" / "thematic-stage13.db")
    for original in protected:
        if target == original.resolve() or (original.exists() and target.samefile(original)):
            raise ValueError("Working databases and their aliases are prohibited")
    if not target.is_file():
        raise ValueError("An existing isolated SQLite file is required")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description="Finalize expired test attempts on an explicit isolated database")
    parser.add_argument("--database", required=True)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args(argv)
    if args.loop and args.interval is None:
        parser.error("--loop requires an explicit --interval")
    if args.interval is not None and (not math.isfinite(args.interval) or args.interval <= 0):
        parser.error("--interval must be finite and positive")
    if args.batch_size <= 0 or args.batch_size > 2**63 - 1:
        parser.error("--batch-size must be a positive SQLite integer")
    try:
        path = checked_database(args.database)
    except (OSError, ValueError):
        parser.error("Use an existing isolated database; working databases and aliases are prohibited")
    try:
        with closing(repository.connect(path)) as db:
            while True:
                try:
                    count = service.expire_attempts(db, batch_size=args.batch_size)
                    print(f"finalized={count}", flush=True)
                except sqlite3.Error as error:
                    busy = isinstance(error, sqlite3.OperationalError) and any(
                        word in str(error).lower() for word in ("busy", "locked"))
                    print("error=DB_BUSY" if busy else "error=DATABASE_UNAVAILABLE", file=sys.stderr, flush=True)
                    if not args.loop or not busy:
                        return 1
                if not args.loop:
                    break
                time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    except sqlite3.Error:
        print("error=DATABASE_UNAVAILABLE", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
