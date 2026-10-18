"""Explicit local JSON draft recovery. No app import, dotenv or publication.

Audit by default. Apply requires a NEW private backup directory. The content
transaction serializes recovery with the editor and rolls back both DB and JSON.
"""
from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from core.content_store import Store, _read
from features.tests import repository, service
from features.tests.validation import digest, validate_draft
from scripts.migrate import check_database, connect, fingerprint, migrate


def load_document(source):
    document = _read(Path(source).resolve(strict=True))
    validated = validate_draft(document)
    if validated != document:
        raise ValueError('Validation would change the backup; manual review required')
    if any(q['media_id'] is not None for q in document['questions']):
        raise ValueError('Media references require separate ownership verification')
    return document


def _backup(database, source, directory, db):
    directory = Path(directory).resolve()
    root = database.parent
    if directory == root or directory.is_relative_to(root):
        raise ValueError('Keep the private backup outside the project/content root')
    directory.mkdir(parents=True, exist_ok=False)
    # A separate read connection avoids backup() waiting on our write transaction.
    with closing(connect(database)) as original, \
         closing(sqlite3.connect(directory / 'users-before.db')) as saved:
        original.backup(saved)
        check_database(saved)
        original_hash = fingerprint(db)
        if fingerprint(saved) != original_hash:
            raise ValueError('Backup differs from the locked database')
        with tempfile.TemporaryDirectory(prefix='ege-draft-restore-') as temporary:
            with closing(sqlite3.connect(Path(temporary) / 'restored.db')) as restored:
                saved.backup(restored)
                check_database(restored)
                if fingerprint(restored) != original_hash:
                    raise ValueError('Restore verification failed')
    shutil.copytree(root / 'tests_content', directory / 'tests_content')
    shutil.copyfile(source, directory / 'source.json')
    manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root / 'tests_content').rglob('*') if p.is_file()}
    for relative, checksum in manifest.items():
        if hashlib.sha256((directory / relative).read_bytes()).hexdigest() != checksum:
            raise ValueError('Content backup verification failed')
    (directory / 'verification.json').write_text(json.dumps({
        'database_fingerprint': original_hash, 'content_files': manifest,
        'restore_verified': True,
        'source_sha256': hashlib.sha256(Path(source).read_bytes()).hexdigest(),
    }, indent=2), encoding='utf-8')


def recover(source, database, *, actor_id, apply=False, backup_directory=None):
    source = Path(source).resolve(strict=True)
    database = Path(database).resolve(strict=True)
    root = database.parent
    configured = os.environ.get('EGEVOLUTION_CONTENT_ROOT')
    if configured and Path(configured).resolve() != root:
        raise ValueError('Recovery requires content next to the explicit database')
    document = load_document(source)
    if migrate(database)['pending']:
        raise ValueError('Database migrations must already be complete')
    if (root / '.content-runtime/journal.json').exists():
        raise ValueError('Pending content recovery requires separate review')
    with closing(repository.connect(database)) as db:
        # Same lock/transaction as normal editor saves; create + save are atomic.
        with repository.transaction(db):
            user = db.execute('SELECT is_admin FROM users WHERE id=?', (actor_id,)).fetchone()
            if user is None or user[0] != 1:
                raise ValueError('An existing local administrator is required')
            store = Store(db, 'tests')  # read-only inspection; no registration
            matches = []
            for parent in store.rows('tests'):
                draft = json.loads(store.get('test_drafts', parent['id'])['document_json'])
                if draft == document:
                    matches.append(parent)
                elif draft['title'] == document['title']:
                    raise ValueError('A different/partial test has this title; no overwrite allowed')
            if len(matches) > 1:
                raise ValueError('Duplicate matching tests require manual review')
            if matches:
                parent = matches[0]
                if parent['publication_state'] != 'draft' or parent['current_version_id'] is not None:
                    raise ValueError('Matching test is already published; no changes made')
                return {'status': 'already_restored', 'test_id': parent['id'],
                        'questions': len(document['questions']), 'publication_state': 'draft'}
            key = 'local-recovery-' + hashlib.sha256(source.read_bytes()).hexdigest()
            if repository.get_operation(db, actor_id, 'local-recovery', key):
                raise ValueError('This backup was restored earlier and subsequently changed; no duplicate created')
            if not apply:
                return {'status': 'ready', 'questions': len(document['questions']),
                        'existing_tests': len(store.rows('tests'))}
            if backup_directory is None:
                raise ValueError('Apply requires a new verified backup directory')
            _backup(database, source, backup_directory, db)
            now = service.now_ms()
            service._representable(document, now)
            ident = repository.create_test_in_transaction(db, {}, actor_id=actor_id, now=now)
            repository.save_draft_in_transaction(db, ident, document,
                expected_revision=1, actor_id=actor_id, now=now)
            repository.record_operation_in_transaction(db, actor_id, 'local-recovery',
                key, digest(document), ident, now)
            if (repository.get_draft(db, ident)['document'] != document or
                    repository.get_test(db, ident)['publication_state'] != 'draft'):
                raise ValueError('Restored draft differs from backup')
            row_factory = db.row_factory
            try:
                db.row_factory = None  # migration checker expects sqlite tuples
                check_database(db)
            finally:
                db.row_factory = row_factory
            result = {'status': 'restored', 'test_id': ident,
                      'questions': len(document['questions']), 'publication_state': 'draft'}
    # A new connection reloads persisted JSON, not the transaction's cached store.
    with closing(connect(database)) as db:
        if json.loads(Store(db, 'tests').get('test_drafts', result['test_id'])['document_json']) != document:
            raise ValueError('Persisted draft verification failed; inspect backup before retrying')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--actor-id', required=True, type=int)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-directory', type=Path)
    args = parser.parse_args()
    result = recover(args.source, args.database, actor_id=args.actor_id,
                     apply=args.apply, backup_directory=args.backup_directory)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
