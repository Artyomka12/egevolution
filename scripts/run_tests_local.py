"""Explicit localhost rehearsal using NEW synthetic data, never working databases.

The command creates a fresh OS-temp fixture and optionally starts an independent
timeout worker. It never reuses an existing Flask process. No dotenv is read.
"""
import argparse
import ast
from contextlib import ExitStack, closing
import importlib.util
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def make_fixture(directory):
    from werkzeug.security import generate_password_hash
    from scripts.migrate import migrate
    path = directory / "fixture.db"
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    init = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "init_db")
    with closing(sqlite3.connect(path)) as db:
        for node in ast.walk(init):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "execute" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and node.args[0].value.strip().startswith("CREATE TABLE")):
                db.execute(node.args[0].value)
        password = generate_password_hash("local-tests-only")
        db.executemany("INSERT INTO users(id,username,password_hash,name,is_admin) VALUES(?,?,?,?,?)", [
            (1, "tests-admin", password, "Локальный преподаватель", 1),
            (2, "tests-student", password, "Локальный ученик", 0),
            (3, "tests-other", password, "Другой локальный ученик", 0)])
        db.commit()
        with closing(sqlite3.connect(directory / "before.db")) as saved:
            db.backup(saved)
    legacy = directory / 'legacy-migrations'
    legacy.mkdir()
    for name in ('001_thematic.sql','002_tests.sql'):
        shutil.copyfile(ROOT/'migrations'/name, legacy/name)
    migrate(path, apply=True, backup=directory / "before.db", offline=True, directory=legacy)
    from scripts.json_content_migration import build_candidate
    candidate = Path(tempfile.mkdtemp(prefix='ege-json-fixture-')).resolve()/'candidate'
    build_candidate(path,candidate)
    return candidate/'users.db'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="Local port; 0 selects a free port")
    parser.add_argument("--worker-interval", type=float,
                        help="Explicit local worker interval in seconds; omission keeps new starts disabled")
    parser.add_argument("--create-only", action="store_true", help="Create a synthetic fixture without starting processes")
    parser.add_argument("--stop-on-stdin-close", action="store_true",
                        help="Automation: stop this fixture and its worker when stdin closes")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("Invalid port")
    if args.worker_interval is not None and (args.worker_interval <= 0 or not __import__('math').isfinite(args.worker_interval)):
        parser.error("Worker interval must be finite and positive")
    directory = Path(tempfile.mkdtemp(prefix="ege-tests-site-")).resolve()
    path = make_fixture(directory)
    print("Synthetic fixture:", directory, flush=True)
    if args.create_only:
        return 0

    environment = {key: os.environ[key] for key in (
        "SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP",
        "SystemDrive", "USERPROFILE", "LOCALAPPDATA", "APPDATA") if key in os.environ}
    environment.update(SECRET_KEY=secrets.token_hex(32), SITE_PASSWORD="local-tests-only",
                       ADMIN_USERNAME="tests-admin", ADMIN_PASSWORD="local-tests-only",
                       EGEVOLUTION_LOCAL_CHECK="1", EGEVOLUTION_DB_PATH=str(path),
                       EGEVOLUTION_CONTENT_ROOT=str(path.parent),
                       PYTHONDONTWRITEBYTECODE="1")
    original_connect = sqlite3.connect

    def guarded(database, *positional, **keywords):
        if os.fspath(database) not in {str(path), path.as_uri() + "?mode=rw"}:
            raise RuntimeError("Only the synthetic fixture database may be opened")
        return original_connect(database, *positional, **keywords)

    worker = None
    with ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, environment, clear=True))
        stack.enter_context(mock.patch("dotenv.load_dotenv", return_value=False))
        stack.enter_context(mock.patch("sqlite3.connect", side_effect=guarded))
        stack.enter_context(mock.patch.object(socket.socket, "connect",
                                            side_effect=RuntimeError("Outbound network disabled")))
        spec = importlib.util.spec_from_file_location("tests_local_app", ROOT / "app.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.EGE_RENUMBER_ARCHIVE = str(directory / "empty-history.json")
        module.app.config.update(TESTS_MEDIA_ROOT=str(directory / "tests-media"),
                                 THEMATIC_MEDIA_ROOT=str(directory / "thematic-media"),
                                 TESTS_STARTS_ENABLED=False,
                                 TESTS_ADMIN_WRITES_ENABLED=True, TESTS_CATALOG_ENABLED=True)
        if args.worker_interval is not None:
            worker = subprocess.Popen([sys.executable, "-B", str(ROOT / "scripts/expire_test_attempts.py"),
                                       "--database", str(path), "--loop", "--interval", str(args.worker_interval)],
                                      cwd=ROOT, env=environment,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        @module.app.before_request
        def local_worker_health():
            module.app.config["TESTS_STARTS_ENABLED"] = worker is not None and worker.poll() is None

        from werkzeug.serving import make_server
        server = make_server("127.0.0.1", args.port, module.app, threaded=True)
        print(f"Local tests site: http://127.0.0.1:{server.server_port}", flush=True)
        print("Synthetic logins: tests-admin / tests-student; password: local-tests-only", flush=True)
        if args.stop_on_stdin_close:
            import threading

            def stop_on_eof():
                sys.stdin.read()
                server.shutdown()

            threading.Thread(target=stop_on_eof, daemon=True).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            if worker is not None:
                worker.terminate()
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
