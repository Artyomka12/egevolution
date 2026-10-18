"""Offline registration of an additive, reviewed test package; audit by default.

Never imports app/.env, modifies JSON, applies migrations or replaces a database.
Run as a module. --pysqlite3 selects the deployment SQLite before domain imports.
"""
from contextlib import closing, contextmanager
from collections import Counter
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


@contextmanager
def content_at(root):
    old = os.environ.get('EGEVOLUTION_CONTENT_ROOT')
    os.environ['EGEVOLUTION_CONTENT_ROOT'] = str(root)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop('EGEVOLUTION_CONTENT_ROOT', None)
        else:
            os.environ['EGEVOLUTION_CONTENT_ROOT'] = old


def file_hashes(root):
    result = {}
    for path in (root / 'tests_content').rglob('*'):
        if path.is_symlink() or getattr(path.stat(), 'st_file_attributes', 0) & 1024:
            raise ValueError('Linked content is not supported')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def database_rows(db):
    # Compare values internally; never print accounts, progress or student answers.
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return {name: Counter(tuple(row) for row in db.execute('SELECT * FROM "' + name.replace('"', '""') + '"'))
            for name in tables}


def check_additions(before, after, allowed, marker):
    if before.keys() != after.keys():
        raise ValueError('Database table set changed')
    for table in before:
        if table == 'sqlite_sequence':
            old, new = before[table], after[table]
            # Counter keys are (table_name, sequence); compare unaffected counters.
            protected = lambda rows: {r for r in rows if r[0] not in allowed}
            if protected(old) != protected(new):
                raise ValueError('Unrelated SQLite sequence changed')
            old_seq, new_seq = dict(old.keys()), dict(new.keys())
            if any(new_seq.get(k, -1) < v for k, v in old_seq.items()):
                raise ValueError('SQLite sequence decreased')
            continue
        if before[table] - after[table]:
            raise ValueError('Existing rows changed: ' + table)
        added = after[table] - before[table]
        if table == 'content_commits':
            if any(row != (marker,) or count != 1 for row, count in added.items()):
                raise ValueError('Unexpected content receipt')
        elif table in allowed:
            if any(row[0] not in allowed[table] or count != 1 for row, count in added.items()):
                raise ValueError('Unrelated identity added: ' + table)
        elif added:
            raise ValueError('Unrelated rows added: ' + table)


def backup_verified(database, root, directory, expected):
    import sqlite3
    from scripts.migrate import connect, check_database, fingerprint
    directory = Path(directory).resolve()
    if directory == root or directory.is_relative_to(root) or directory.is_relative_to(database.parent):
        raise ValueError('Use a new private backup directory outside content/database roots')
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    with closing(connect(database)) as source, closing(sqlite3.connect(directory / 'users-before.db')) as saved:
        source.backup(saved)
        check_database(saved)
        if fingerprint(saved) != expected:
            raise ValueError('Backup differs from locked database')
        with closing(sqlite3.connect(':memory:')) as restored:
            saved.backup(restored)
            check_database(restored)
            if fingerprint(restored) != expected:
                raise ValueError('Backup restore verification failed')
    manifest = file_hashes(root)
    shutil.copytree(root / 'tests_content', directory / 'tests_content')
    if file_hashes(directory) != manifest:
        raise ValueError('Content backup differs')
    (directory / 'verification.json').write_text(json.dumps({
        'restore_verified': True, 'database_fingerprint': expected, 'content_files': manifest,
    }, indent=2) + '\n', encoding='utf-8')


def register(database, content_root, previous_content_root, test_id, *,
             apply=False, confirm_offline=False, backup_directory=None):
    import sqlite3
    from core.content_store import Store, _lock, digest
    from scripts.migrate import connect, check_database, fingerprint, migrate
    database = Path(database).resolve(strict=True)
    root = Path(content_root).resolve(strict=True)
    previous = Path(previous_content_root).resolve(strict=True)
    if apply and (not confirm_offline or not backup_directory):
        raise ValueError('Apply requires --confirm-offline and a new --backup-directory')
    if migrate(database)['pending']:
        raise ValueError('Complete, matching migration history is required')
    # Preflight locks the live old content; apply locks the installed new content.
    live = root if apply else previous
    with _lock(live), closing(connect(database, 'rw' if apply else 'ro')) as db:
        db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        try:
            for directory in {root, previous, database.parent}:
                if (directory / '.content-runtime/journal.json').exists():
                    raise ValueError('Pending content journal; separate recovery required')
            incoming_hashes, previous_hashes = file_hashes(root), file_hashes(previous)
            with content_at(previous):
                old = Store(db, 'tests')
            with content_at(root):
                incoming = Store(db, 'tests')
            target = incoming.get('tests', test_id)
            if target is None:
                raise ValueError('Target test is absent from package')
            old_ids = [r['id'] for r in old.rows('tests')]
            new_ids = [r['id'] for r in incoming.rows('tests')]
            if set(new_ids) != set(old_ids) | {test_id}:
                raise ValueError('Package removes or adds unrelated tests')
            if [i for i in new_ids if i in old_ids] != old_ids:
                raise ValueError('Existing test order changed')
            catalog_key = 'tests_content/catalog.json'
            for path, checksum in previous_hashes.items():
                if path != catalog_key and incoming_hashes.get(path) != checksum:
                    raise ValueError('Existing test file differs: ' + path)
            old_catalog = old.original_files[previous / catalog_key]
            new_catalog = incoming.original_files[root / catalog_key]
            for key in set(old_catalog) | set(new_catalog):
                if key not in ('material_ids', 'catalog_state') and old_catalog.get(key) != new_catalog.get(key):
                    raise ValueError('Unrelated catalog data changed: ' + key)
            if new_catalog['catalog_state']['revision'] < old_catalog['catalog_state']['revision']:
                raise ValueError('Catalog revision decreased')
            versions = [r for r in incoming.rows('test_versions') if r['test_id'] == test_id]
            version_ids = {r['id'] for r in versions}
            questions = [r for r in incoming.rows('test_version_questions') if r['version_id'] in version_ids]
            question_ids = {r['id'] for r in questions}
            draft = json.loads(incoming.get('test_drafts', test_id)['document_json'])
            for ident in old_ids:
                if ident != test_id:
                    existing_draft = json.loads(old.get('test_drafts', ident)['document_json'])
                    if existing_draft['title'] == draft['title']:
                        raise ValueError('Possible duplicate test title; review IDs before transfer')
            if any(q.get('media_id') for q in questions + draft['questions']):
                raise ValueError('Media transfer requires a separately reviewed procedure')
            allowed = {'tests': {test_id}, 'test_versions': version_ids,
                       'test_version_questions': question_ids,
                       'test_question_options': {r['id'] for r in incoming.rows('test_question_options')
                                                if r['question_id'] in question_ids}}
            target_files = {p.relative_to(root).as_posix(): value for p, value in incoming.original_files.items()
                            if p.is_relative_to(root / 'tests_content' / ('test_' + str(test_id)))}
            if set(incoming_hashes) - set(previous_hashes) - set(target_files):
                raise ValueError('Unrelated new content files in package')
            marker = 'test-transfer:' + str(test_id) + ':' + digest(target_files)
            receipt = db.execute('SELECT 1 FROM content_commits WHERE id=?', (marker,)).fetchone()
            exists = db.execute('SELECT 1 FROM tests WHERE id=?', (test_id,)).fetchone()
            if exists and test_id not in old_ids and not receipt:
                raise ValueError('Test ID conflict: no previous JSON or matching transfer receipt')
            before, before_hash = database_rows(db), fingerprint(db)
            # Rehearse the exact registration on a SQLite Backup API copy first.
            with closing(sqlite3.connect(':memory:', isolation_level=None)) as rehearsal:
                with closing(connect(database)) as source:
                    source.backup(rehearsal)
                if fingerprint(rehearsal) != before_hash:
                    raise ValueError('Database changed during audit; retry offline')
                rehearsal.execute('PRAGMA foreign_keys=ON')
                rehearsal.execute('PRAGMA recursive_triggers=ON')
                rehearsal.execute('BEGIN IMMEDIATE')
                with content_at(root):
                    Store(rehearsal, 'tests').register()
                rehearsal.execute('INSERT OR IGNORE INTO content_commits(id) VALUES (?)', (marker,))
                check_database(rehearsal)
                planned = database_rows(rehearsal)
                check_additions(before, planned, allowed, marker)
            unchanged = before == planned
            result = dict(status='already_registered' if unchanged else 'ready', test_id=test_id,
                          publication_state=target['publication_state'],
                          current_version_id=target['current_version_id'],
                          versions=len(versions), questions=len(draft['questions']))
            if backup_directory and not (apply and unchanged):
                backup_verified(database, live, backup_directory, before_hash)
            if apply and not unchanged:
                with content_at(root):
                    Store(db, 'tests').register()
                db.execute('INSERT OR IGNORE INTO content_commits(id) VALUES (?)', (marker,))
                check_database(db)
                if database_rows(db) != planned:
                    raise ValueError('Registration differs from verified rehearsal')
                result['status'] = 'registered'
            if file_hashes(root) != incoming_hashes or file_hashes(previous) != previous_hashes:
                raise ValueError('JSON changed during registration')
            db.execute('COMMIT' if apply else 'ROLLBACK')
            return result
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--content-root', required=True)
    parser.add_argument('--previous-content-root', required=True)
    parser.add_argument('--test-id', type=int, required=True)
    parser.add_argument('--backup-directory')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm-offline', action='store_true')
    parser.add_argument('--pysqlite3', action='store_true')
    args = vars(parser.parse_args())
    if args.pop('pysqlite3'):
        import pysqlite3
        sys.modules['sqlite3'] = pysqlite3
    try:
        print(json.dumps(register(**args), ensure_ascii=False))
    except (ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
