"""Run local unittest fixtures with DB, dotenv and network isolation.

This command never starts the website or applies migrations to working data.
Only test fixtures may create and migrate databases under the OS temp directory.
"""
import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="test_tests_*.py")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    temp_root = Path(tempfile.gettempdir()).resolve()
    original_connect = sqlite3.connect

    def isolated_connect(database, *positional, **keywords):
        text = os.fspath(database)
        if text != ":memory:":
            if text.startswith("file:"):
                parsed = urlsplit(text)
                if parsed.netloc:
                    raise AssertionError("Network SQLite paths are forbidden")
                text = unquote(parsed.path)
                if os.name == "nt" and len(text) > 2 and text[0] == "/" and text[2] == ":":
                    text = text[1:]
            path = Path(text).resolve()
            if not path.is_relative_to(temp_root):
                raise AssertionError("SQLite connection outside temporary fixtures is forbidden")
            for name in ("users.db", ".local-data/dev-users.db", ".local-data/thematic-stage13.db"):
                protected = ROOT / name
                if path.exists() and protected.exists() and path.samefile(protected):
                    raise AssertionError("A working database alias is forbidden")
        return original_connect(database, *positional, **keywords)

    # Keep OS execution essentials; never inherit application credentials or DB paths.
    environment = {key: os.environ[key] for key in (
        "SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP",
        "SystemDrive", "USERPROFILE", "LOCALAPPDATA", "APPDATA") if key in os.environ}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    with ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, environment, clear=True))
        stack.enter_context(mock.patch("dotenv.load_dotenv", return_value=False))
        stack.enter_context(mock.patch("sqlite3.connect", side_effect=isolated_connect))
        stack.enter_context(mock.patch.object(socket.socket, "connect",
                                            side_effect=AssertionError("Network forbidden in local fixtures")))
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=args.pattern)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
