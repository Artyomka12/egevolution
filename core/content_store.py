"""JSON curriculum storage; SQLite retains identities and learner operations only.

All readers/writers take the same OS lock. A durable file journal plus a SQLite
commit marker recovers interrupted multi-file publication without storing content
in SQLite. The application never serves these directories as public static files.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid


class ContentError(ValueError):
    pass


TABLES = {
    'thematic': ('thematic_variants', 'thematic_versions', 'thematic_version_items',
                 'thematic_media', 'thematic_item_media', 'thematic_drafts', 'thematic_catalog_state'),
    'tests': ('tests', 'test_versions', 'test_version_questions', 'test_question_options',
              'test_accepted_answers', 'test_drafts', 'test_media', 'test_media_links', 'test_catalog_state'),
}
KEYS = {'thematic_drafts': ('variant_id',), 'test_drafts': ('test_id',),
        'thematic_catalog_state': ('singleton_id',), 'test_catalog_state': ('singleton_id',),
        'thematic_item_media': ('item_id', 'role', 'position'),
        'test_media_links': ('test_id', 'media_id')}
IDENTITIES = {'thematic_variants': ('id',), 'thematic_versions': ('id', 'variant_id'),
              'thematic_version_items': ('id', 'version_id'), 'thematic_media': ('id',),
              'tests': ('id',), 'test_versions': ('id', 'test_id'),
              'test_version_questions': ('id', 'version_id'),
              'test_question_options': ('id', 'question_id'), 'test_media': ('id', 'created_by')}
AUTHORS = {'created_by', 'published_by', 'updated_by'}
DEFAULTS = {
    'thematic_variants': dict(state='draft', current_version_id=None, sort_order=0,
        revision=1, created_by=None, created_at=0, updated_at=0, deleted_at=None),
    'tests': dict(publication_state='draft', current_version_id=None, sort_order=0,
        revision=1, created_by=None, created_at=0, updated_at=0),
    'thematic_versions': dict(sealed=0, published_by=None, snapshot_schema_version=1),
    'test_versions': dict(sealed=0, published_by=None, schema_version=1),
    'thematic_drafts': dict(revision=1, based_on_version_id=None, updated_by=None, updated_at=0),
    'test_drafts': dict(revision=1, based_on_version_id=None, updated_by=None, updated_at=0),
    'test_media': dict(created_by=None, state='staged', alt_text=''),
    'test_version_questions': dict(code_text=None, free_input_mode=None, media_id=None, max_points=1),
}
_state = threading.local()
_mutex = threading.RLock()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def database_path(db):
    paths = [r[2] for r in db.execute('PRAGMA database_list') if r[1] == 'main']
    if not paths or not paths[0]:
        raise ContentError('JSON storage requires an explicit file-backed database')
    return Path(paths[0]).resolve()


def content_root(db):
    return Path(os.environ.get('EGEVOLUTION_CONTENT_ROOT') or database_path(db).parent).resolve()


def _read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContentError('Duplicate JSON key')
            result[key] = value
        return result
    try:
        if path.is_symlink() or (getattr(path.stat(), 'st_file_attributes', 0) & 1024):
            raise ContentError('Linked content files are not supported')
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ContentError('Invalid JSON number')))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContentError('Missing or damaged JSON content: ' + str(path)) from error


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != 'nt':
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _lock(root):
    runtime = _safe(root, '.content-runtime')
    runtime.mkdir(parents=True, exist_ok=True)
    with _mutex, _safe(root, '.content-runtime/lock').open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.tell() == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            deadline = time.monotonic() + 15
            while True:
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ContentError('Content storage is busy')
                    time.sleep(.02)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield runtime
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def _safe(root, relative):
    if not isinstance(relative, str): raise ContentError('Unsafe content path')
    path = root / relative
    if (not isinstance(relative, str) or ':' in relative or '\\' in relative
            or Path(relative).is_absolute() or '..' in Path(relative).parts
            or not path.resolve().is_relative_to(root)):
        raise ContentError('Unsafe content path')
    for parent in (path, *path.parents):
        if parent == root.parent: break
        if parent.exists() and (parent.is_symlink() or getattr(parent.stat(), 'st_file_attributes', 0) & 1024):
            raise ContentError('Linked content paths are not supported')
    return path


def _recover(db, root, runtime):
    journal = runtime / 'journal.json'
    if not journal.exists():
        return
    saved = _read(journal)
    if not isinstance(saved,dict) or not isinstance(saved.get('files'),list) or not isinstance(saved.get('id'),str):
        raise ContentError('Damaged recovery journal; manual recovery required')
    if saved.get('database') != str(database_path(db)):
        raise ContentError('Recovery journal belongs to another database; manual recovery required')
    paths = set()
    for entry in saved['files']:
        if not isinstance(entry,dict) or not isinstance(entry.get('path'),str): raise ContentError('Damaged recovery entry')
        relative = entry['path']
        if (not re.fullmatch(r'(?:thematic_variants/(?:catalog\.json|variant_[1-9][0-9]*/(?:material\.json|versions/[1-9][0-9]*\.json))|tests_content/(?:catalog\.json|test_[1-9][0-9]*/(?:material\.json|versions/[1-9][0-9]*\.json)))',relative)
                or relative in paths or any(k not in entry or (entry[k] is not None and not isinstance(entry[k],dict)) for k in ('old','new'))):
            raise ContentError('Unsafe recovery entry; manual recovery required')
        _safe(root,relative)
        paths.add(relative)
    committed = db.execute('SELECT 1 FROM content_commits WHERE id=?', (saved['id'],)).fetchone()
    for entry in saved['files']:
        path = _safe(root, entry['path'])
        value = entry['new'] if committed else entry['old']
        if value is None:
            if path.exists():
                path.unlink()
        else:
            _write(path, value)
    journal.unlink()


def _active(db):
    active = getattr(_state, 'active', None)
    return active if active and active['db'] is db else None


@contextmanager
def transaction(db):
    active = _active(db)
    if active:
        yield db
        return
    if getattr(_state, 'active', None):
        raise ContentError('Nested content transactions across databases are not supported')
    if db.in_transaction:
        raise ContentError('Acquire content transaction before starting SQLite transaction')
    root = content_root(db)
    with _lock(root) as runtime:
        _recover(db, root, runtime)
        db.execute('BEGIN IMMEDIATE')
        active = {'db': db, 'root': root, 'stores': {}}
        _state.active = active
        journal = runtime / 'journal.json'
        try:
            yield db
            changes = []
            for store in active['stores'].values():
                if store.dirty:
                    store.validate()
                    new_files = store.files()
                    for path in set(store.original_files) | set(new_files):
                        old, new = store.original_files.get(path), new_files.get(path)
                        if old != new:
                            changes.append({'path': path.relative_to(root).as_posix(), 'old': old, 'new': new})
                    store.register()
            if changes:
                token = uuid.uuid4().hex
                _write(journal, {'id': token, 'database': str(database_path(db)), 'files': changes})
                for entry in changes:
                    path = _safe(root, entry['path'])
                    if entry['new'] is None:
                        if path.exists(): path.unlink()
                    else:
                        _write(path, entry['new'])
                db.execute('INSERT INTO content_commits(id) VALUES (?)', (token,))
            db.commit()
            if journal.exists(): journal.unlink()
        except BaseException:
            db.rollback()
            _recover(db, root, runtime)
            raise
        finally:
            _state.active = None


class Store:
    def __init__(self, db, domain):
        if domain not in TABLES: raise ContentError('Unknown content domain')
        self.db, self.domain = db, domain
        self.root = content_root(db) / ('thematic_variants' if domain == 'thematic' else 'tests_content')
        self.media_root = self.root / 'media'
        self.data = {name: [] for name in TABLES[domain]}
        self.original_files = {}
        self.counters = {}
        self.dirty = False
        try:
            self._load()
        except (KeyError, TypeError, AttributeError, IndexError, ValueError) as error:
            if isinstance(error, ContentError): raise
            raise ContentError('Malformed JSON content structure') from error

    @property
    def parent_table(self): return 'thematic_variants' if self.domain == 'thematic' else 'tests'

    @property
    def version_table(self): return 'thematic_versions' if self.domain == 'thematic' else 'test_versions'

    def _load(self):
        catalog_path = self.root / 'catalog.json'
        _safe(content_root(self.db), catalog_path.relative_to(content_root(self.db)).as_posix())
        catalog = _read(catalog_path)
        if catalog.get('schema_version') != 1 or catalog.get('domain') != self.domain:
            raise ContentError('Unsupported JSON catalog')
        self.original_files[catalog_path] = deepcopy(catalog)
        self.counters = catalog.get('counters', {})
        self.data['thematic_catalog_state' if self.domain == 'thematic' else 'test_catalog_state'] = [catalog['catalog_state']]
        self.data['thematic_media' if self.domain == 'thematic' else 'test_media'] = catalog.get('media', [])
        if not isinstance(catalog['material_ids'], list) or len(set(catalog['material_ids'])) != len(catalog['material_ids']):
            raise ContentError('Duplicate or invalid material list')
        for ident in catalog['material_ids']:
            if type(ident) is not int or ident <= 0: raise ContentError('Invalid material identity')
            folder = self.root / (('variant_' if self.domain == 'thematic' else 'test_') + str(ident))
            path = folder / 'material.json'
            _safe(content_root(self.db), path.relative_to(content_root(self.db)).as_posix())
            document = _read(path)
            self.original_files[path] = deepcopy(document)
            if document.get('schema_version') != 1 or document['material']['id'] != ident:
                raise ContentError('Material identity mismatch')
            self.data[self.parent_table].append(document['material'])
            foreign = 'variant_id' if self.domain == 'thematic' else 'test_id'
            if document.get('draft'):
                if document['draft'][foreign] != ident: raise ContentError('Draft belongs to another material')
                self.data['thematic_drafts' if self.domain == 'thematic' else 'test_drafts'].append(document['draft'])
            if self.domain == 'tests':
                if any(link['test_id'] != ident for link in document.get('media_links', [])): raise ContentError('Media link belongs to another test')
                self.data['test_media_links'].extend(document.get('media_links', []))
            for version_id in document['version_ids']:
                if type(version_id) is not int or version_id <= 0: raise ContentError('Invalid version identity')
                path = folder / 'versions' / (str(version_id) + '.json')
                _safe(content_root(self.db), path.relative_to(content_root(self.db)).as_posix())
                version = _read(path)
                self.original_files[path] = deepcopy(version)
                if version.get('schema_version') != 1 or version['version']['id'] != version_id:
                    raise ContentError('Version identity mismatch')
                foreign = 'variant_id' if self.domain == 'thematic' else 'test_id'
                if version['version'][foreign] != ident: raise ContentError('Version belongs to another material')
                self.data[self.version_table].append(version['version'])
                allowed = ({'thematic_version_items','thematic_item_media'} if self.domain == 'thematic'
                           else {'test_version_questions','test_question_options','test_accepted_answers'})
                if set(version['tables']) != allowed: raise ContentError('Unexpected version content tables')
                if self.domain == 'tests':
                    questions = {q['id'] for q in version['tables']['test_version_questions']}
                    if any(row['question_id'] not in questions for name in ('test_question_options','test_accepted_answers') for row in version['tables'][name]):
                        raise ContentError('Question content belongs to another version file')
                for table, rows in version['tables'].items():
                    if not isinstance(rows, list): raise ContentError('Invalid content rows')
                    if any('version_id' in row and row['version_id'] != version_id for row in rows):
                        raise ContentError('Version content in wrong file')
                    self.data[table].extend(rows)
        self.validate()

    def rows(self, table):
        if table not in self.data: raise ContentError('Unknown content collection')
        result = deepcopy(self.data[table])
        if table == 'test_media':
            owners = dict(self.db.execute('SELECT id,created_by FROM test_media'))
            for row in result: row['created_by'] = owners.get(row['id'], row.get('created_by'))
        return result

    @staticmethod
    def key(table, row):
        fields = KEYS.get(table, ('id',))
        values = tuple(row[f] for f in fields)
        return values[0] if len(values) == 1 else values

    def get(self, table, ident):
        return next((r for r in self.rows(table) if self.key(table, r) == ident), None)

    def _write_check(self):
        active = _active(self.db)
        if not active or active['stores'].get(self.domain) is not self:
            raise ContentError('Content mutation requires the current transaction store')

    def next_id(self, table):
        self._write_check()
        existing = {r.get('id') for r in self.data[table]}
        ident = secrets.randbelow(2**52 - 2**40) + 2**40
        while ident in existing: ident = secrets.randbelow(2**52 - 2**40) + 2**40
        return ident

    def insert(self, table, row):
        self._write_check(); row = {**DEFAULTS.get(table, {}), **deepcopy(row)}
        if table not in self.data: raise ContentError('Unknown content collection')
        if table not in KEYS and 'id' not in row: row['id'] = self.next_id(table)
        ident = self.key(table, row)
        if self.get(table, ident) is not None: raise sqlite3.IntegrityError('Duplicate content identity')
        if table == self.version_table:
            if row.get('sealed') != 0: raise sqlite3.IntegrityError('Version must be assembled before sealing')
            if self.domain == 'thematic':
                parent = self.get(self.parent_table, row['variant_id'])
                if parent and parent['state'] in ('deleting','deleted'): raise sqlite3.IntegrityError('Deleted material')
        self._guard_child(table, row)
        self.data[table].append(row); self.dirty = True
        self._register_row(table, row)
        return ident

    def update(self, table, ident, **fields):
        self._write_check()
        for row in self.data[table]:
            if self.key(table, row) == ident:
                self._immutable(table, row, fields)
                row.update(deepcopy(fields)); self.dirty = True
                return
        raise ContentError('Content record missing')

    def delete(self, table, ident):
        self._write_check()
        row = next((r for r in self.data[table] if self.key(table,r) == ident), None)
        if row is not None:
            if table == 'tests':
                versions = {v['id'] for v in self.data['test_versions'] if v['test_id'] == ident}
                questions = {q['id'] for q in self.data['test_version_questions'] if q['version_id'] in versions}
                for name in ('test_question_options','test_accepted_answers'):
                    self.data[name] = [r for r in self.data[name] if r['question_id'] not in questions]
                self.data['test_version_questions'] = [r for r in self.data['test_version_questions'] if r['version_id'] not in versions]
                self.data['test_versions'] = [r for r in self.data['test_versions'] if r['id'] not in versions]
                for name in ('test_drafts','test_media_links'):
                    self.data[name] = [r for r in self.data[name] if r['test_id'] != ident]
            else:
                self._guard_child(table, row)
                if table == self.version_table and row.get('sealed'):
                    raise sqlite3.IntegrityError('Historical version must be retained')
                if table == 'thematic_variants' and any(v['variant_id'] == ident for v in self.data['thematic_versions']):
                    raise sqlite3.IntegrityError('Historical material must be retained')
                if table in ('thematic_media','test_media') and self._media_referenced(table,ident):
                    raise sqlite3.IntegrityError('Referenced media must be retained')
            self.data[table].remove(row); self.dirty = True

    def _media_referenced(self, table, ident):
        names = ('thematic_item_media',) if table == 'thematic_media' else ('test_media_links','test_version_questions')
        return any(r.get('media_id') == ident for name in names for r in self.data[name])

    def _guard_child(self, table, row):
        children = ('thematic_version_items','thematic_item_media','test_version_questions',
                    'test_question_options','test_accepted_answers')
        if table not in children: return
        version_id = row.get('version_id')
        if table in ('test_question_options','test_accepted_answers'):
            question = self.get('test_version_questions',row['question_id'])
            if question is None: raise sqlite3.IntegrityError('Missing parent question')
            version_id = question['version_id']
        version = self.get(self.version_table,version_id)
        if version is None: raise sqlite3.IntegrityError('Missing parent version')
        if version.get('sealed'): raise sqlite3.IntegrityError('Immutable published content')

    def _immutable(self, table, row, fields):
        if any(k in fields and fields[k] != row[k] for k in KEYS.get(table, ('id',))):
            raise sqlite3.IntegrityError('Immutable content identity')
        if table == self.version_table and row.get('sealed') and any(row.get(k) != v for k,v in fields.items() if k not in AUTHORS):
            raise sqlite3.IntegrityError('Immutable published version')
        if table in ('thematic_version_items','thematic_item_media','test_version_questions','test_question_options','test_accepted_answers'):
            if any(row.get(k) != v for k,v in fields.items()): raise sqlite3.IntegrityError('Immutable version content')
        if table == 'thematic_variants' and row.get('state') == 'deleted' and fields.get('state','deleted') != 'deleted':
            raise sqlite3.IntegrityError('Deleted thematic variant cannot be restored')
        if table in ('thematic_media','test_media'):
            mutable = {'created_by','state'} if table == 'test_media' else set()
            if any(row.get(k) != v for k,v in fields.items() if k not in mutable):
                raise sqlite3.IntegrityError('Immutable media')
            if row.get('state') == 'ready' and fields.get('state','ready') != 'ready':
                raise sqlite3.IntegrityError('Ready media cannot be reverted')

    def _register_row(self, table, row):
        columns = IDENTITIES.get(table)
        if not columns: return
        existing = self.db.execute('SELECT * FROM '+table+' WHERE id=?',(row['id'],)).fetchone()
        if existing is None:
            self.db.execute('INSERT INTO '+table+' ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',tuple(row.get(k) for k in columns))
        else:
            names = [r[1] for r in self.db.execute('PRAGMA table_info('+table+')')]
            old = dict(zip(names, tuple(existing)))
            for k in columns:
                if k != 'created_by' and old[k] != row[k]: raise ContentError('Conflicting stable JSON identity')

    def register(self):
        for table in TABLES[self.domain]:
            for row in self.data[table]: self._register_row(table,row)
            if table in IDENTITIES:
                present = {row['id'] for row in self.data[table]}
                if any(row[0] not in present for row in self.db.execute('SELECT id FROM '+table)):
                    raise ContentError('Registered JSON content is missing: '+table)
        for path, document in self.files().items():
            if 'version' not in document or not document['version'].get('sealed'): continue
            ident = document['version']['id']; expected = digest(document)
            if self.domain == 'tests':
                # Media metadata is not duplicated in version JSON. Include its
                # fingerprint in the SQL identity checksum so changing a shared
                # image descriptor cannot silently alter historical questions.
                media_ids = {q.get('media_id') for q in document['tables']['test_version_questions']} - {None}
                descriptors = [{k:v for k,v in row.items() if k not in AUTHORS}
                               for row in self.data['test_media'] if row['id'] in media_ids]
                expected = digest({'version':document,'media':sorted(descriptors,key=lambda row:row['id'])})
            old = self.db.execute('SELECT json_hash FROM '+self.version_table+' WHERE id=?',(ident,)).fetchone()
            if old and old[0] and old[0] != expected: raise ContentError('Immutable JSON version has changed')
            self.db.execute('UPDATE '+self.version_table+' SET json_hash=? WHERE id=?',(expected,ident))
        for ident, stored_hash in self.db.execute('SELECT id,json_hash FROM '+self.version_table):
            if stored_hash and self.get(self.version_table,ident) is None:
                raise ContentError('A historical JSON version is missing')

    def validate(self):
        try:
            self._validate()
        except (KeyError, TypeError, AttributeError, IndexError, ValueError) as error:
            if isinstance(error, ContentError): raise
            raise ContentError('Invalid JSON content: ' + type(error).__name__) from error

    def _validate(self):
        def integer(value, minimum=1):
            if type(value) is not int or not minimum <= value <= 2**53-1:
                raise ContentError('Invalid integer in content')
        def text(value, nonempty=False):
            if not isinstance(value,str) or (nonempty and not value.strip()): raise ContentError('Invalid text in content')
            value.encode('utf-8')
        def positioned(rows):
            positions = [r['position'] for r in rows]
            for position in positions: integer(position)
            if sorted(positions) != list(range(1,len(rows)+1)): raise ContentError('Invalid ordered content positions')
        def json_object(raw):
            text(raw)
            value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ContentError('Invalid JSON number')))
            if not isinstance(value,dict): raise ContentError('Expected JSON object')
            return value
        for table, rows in self.data.items():
            if not isinstance(rows,list): raise ContentError('Content rows must be an array')
            for row in rows:
                if not isinstance(row,dict): raise ContentError('Content row must be an object')
                for name,value in row.items():
                    if name == 'id' or name.endswith('_id'):
                        if value is not None: integer(value)
            keys = [self.key(table,r) for r in rows]
            if len(set(keys)) != len(keys): raise ContentError('Duplicate content identities')
        state = self.data['thematic_catalog_state' if self.domain == 'thematic' else 'test_catalog_state']
        if len(state) != 1 or state[0]['singleton_id'] != 1: raise ContentError('Invalid catalog state')
        integer(state[0]['revision'])
        parents = {r['id'] for r in self.data[self.parent_table]}
        foreign = 'variant_id' if self.domain == 'thematic' else 'test_id'
        versions = {r['id']:r for r in self.data[self.version_table]}
        pairs = set()
        for row in self.data[self.version_table]:
            if row[foreign] not in parents: raise ContentError('Orphan content version')
            integer(row['version_no']); integer(row['question_count']); integer(row['published_at'],0)
            text(row['title'],True); text(row['description'])
            if type(row['sealed']) is not int or row['sealed'] != 1: raise ContentError('Unsealed content cannot be persisted')
            if not re.fullmatch('[0-9a-f]{64}',row['content_hash']): raise ContentError('Invalid content hash')
            pair = (row[foreign],row['version_no'])
            if pair in pairs: raise ContentError('Duplicate version number')
            pairs.add(pair)
        for row in self.data[self.parent_table]:
            integer(row['revision']); integer(row['created_at'],0); integer(row['updated_at'],0)
            if type(row['sort_order']) is not int: raise ContentError('Invalid material order')
            state = row['state'] if self.domain == 'thematic' else row['publication_state']
            allowed = ('draft','published','hidden','deleting','deleted') if self.domain == 'thematic' else ('draft','published','hidden')
            if state not in allowed: raise ContentError('Invalid publication state')
            if state in ('published','hidden') and row.get('current_version_id') is None: raise ContentError('Published material lacks version')
            if self.domain == 'thematic':
                if (state == 'deleted') != (row.get('deleted_at') is not None): raise ContentError('Invalid thematic tombstone')
                if row.get('deleted_at') is not None: integer(row['deleted_at'],0)
                if state == 'deleted' and row.get('current_version_id') is not None: raise ContentError('Deleted material has current version')
            if row.get('current_version_id') is not None:
                version = versions.get(row['current_version_id'])
                if not version or version[foreign] != row['id'] or not version.get('sealed'):
                    raise ContentError('Invalid published version reference')
        media_table = 'thematic_media' if self.domain == 'thematic' else 'test_media'
        media = {r['id']:r for r in self.data[media_table]}
        storage_keys = set()
        for row in media.values():
            key = row['storage_key']
            expected_length = 64 if self.domain == 'thematic' else 32
            if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{'+str(expected_length)+'}', key): raise ContentError('Unsafe media storage key')
            if key in storage_keys: raise ContentError('Duplicate media storage key')
            storage_keys.add(key)
            if not re.fullmatch('[0-9a-f]{64}',row['sha256']): raise ContentError('Invalid media hash')
            integer(row['size_bytes'],0 if self.domain == 'thematic' else 1)
            integer(row['created_at'],0); text(row['mime_type'],True)
            for dimension in ('width','height'):
                if row.get(dimension) is not None: integer(row[dimension])
            if self.domain == 'tests':
                if row['mime_type'] not in ('image/png','image/jpeg','image/gif') or row['size_bytes'] > 5242880:
                    raise ContentError('Invalid test image')
                integer(row['width']); integer(row['height']); text(row['alt_text'])
                if row['state'] not in ('staged','ready'): raise ContentError('Invalid media state')
            else: text(row['original_name'])
        draft_table = 'thematic_drafts' if self.domain == 'thematic' else 'test_drafts'
        for row in self.data[draft_table]:
            if row[foreign] not in parents: raise ContentError('Orphan draft')
            based = row.get('based_on_version_id')
            if based is not None and (based not in versions or versions[based][foreign] != row[foreign]): raise ContentError('Invalid draft base version')
            integer(row['revision']); integer(row['updated_at'],0)
            if self.domain == 'thematic':
                from features.thematic.validation import validate_draft
            else:
                from features.tests.validation import validate_draft
            validate_draft(json_object(row['document_json']))
        if self.domain == 'thematic':
            from features.thematic.validation import validate_snapshot, validate_sources
            items = {r['id']:r for r in self.data['thematic_version_items']}
            for row in items.values():
                if row['version_id'] not in versions: raise ContentError('Orphan thematic item')
                snapshot = json_object(row['snapshot_json']); validate_snapshot(snapshot)
                if any(snapshot[k] != row[k] for k in ('source_task_num','source_task_id','task_type')):
                    raise ContentError('Snapshot identity mismatch')
                if digest(snapshot) != row['snapshot_hash']: raise ContentError('Snapshot hash mismatch')
                links = [link for link in self.data['thematic_item_media'] if link['item_id'] == row['id']]
                actual = []
                for link in links:
                    if link['version_id'] != row['version_id'] or link['media_id'] not in media: raise ContentError('Invalid thematic media reference')
                    actual.append(dict(role=link['role'],position=link['position'],media_id=link['media_id'],
                        sha256=media[link['media_id']]['sha256'],alt_text=link['alt_text'],display_metadata=json_object(link['display_metadata_json'])))
                ordering = lambda value:(value['role'],value['position'])
                if sorted(actual,key=ordering) != sorted(snapshot['materials'],key=ordering): raise ContentError('Snapshot media mismatch')
            if any(r['item_id'] not in items for r in self.data['thematic_item_media']): raise ContentError('Orphan thematic media link')
            for version in versions.values():
                ordered = sorted((r for r in items.values() if r['version_id']==version['id']),key=lambda r:r['position'])
                positioned(ordered); validate_sources(ordered)
                if len(ordered) != version['question_count']: raise ContentError('Incomplete thematic version')
                snapshots = [json_object(r['snapshot_json']) for r in ordered]
                if any(s['grader_version'] != version['grader_version'] or s['snapshot_schema_version'] != version['snapshot_schema_version'] for s in snapshots): raise ContentError('Snapshot schema mismatch')
                if digest(dict(title=version['title'],description=version['description'],items=snapshots)) != version['content_hash']: raise ContentError('Thematic content hash mismatch')
        else:
            from features.tests.validation import validate_publication
            questions = {r['id']:r for r in self.data['test_version_questions']}
            links = {(r['test_id'],r['media_id']) for r in self.data['test_media_links']}
            if any(t not in parents or m not in media for t,m in links): raise ContentError('Orphan test media link')
            for name in ('test_question_options','test_accepted_answers'):
                if any(r['question_id'] not in questions for r in self.data[name]): raise ContentError('Orphan question content')
            for q in questions.values():
                if q['version_id'] not in versions: raise ContentError('Orphan question')
                if type(q['max_points']) is not int or q['max_points'] != 1: raise ContentError('Invalid question score')
                if q.get('media_id') is not None:
                    m = media.get(q['media_id'])
                    if not m or m['state'] != 'ready' or (versions[q['version_id']]['test_id'],m['id']) not in links: raise ContentError('Question media unavailable')
            for version in versions.values():
                if version['schema_version'] != 1: raise ContentError('Unsupported test schema')
                if type(version['show_correct_answers']) is not int or version['show_correct_answers'] not in (0,1): raise ContentError('Invalid answer visibility setting')
                ordered = sorted((q for q in questions.values() if q['version_id']==version['id']),key=lambda q:q['position'])
                positioned(ordered)
                if len(ordered) != version['question_count']: raise ContentError('Incomplete test version')
                document = {k:version[k] for k in ('title','description','time_limit_seconds','attempt_limit')}
                document.update(show_correct_answers=bool(version['show_correct_answers']),questions=[])
                for q in ordered:
                    item = {k:q.get(k) for k in ('title','prompt_text','code_text','question_type','free_input_mode','grading_mode','media_id')}
                    options = sorted((r for r in self.data['test_question_options'] if r['question_id']==q['id']),key=lambda r:r['position'])
                    accepted = sorted((r for r in self.data['test_accepted_answers'] if r['question_id']==q['id']),key=lambda r:r['position'])
                    positioned(options); positioned(accepted)
                    if any(type(o['is_correct']) is not int or o['is_correct'] not in (0,1) for o in options): raise ContentError('Invalid option correctness')
                    item.update(options=[dict(text=o['text'],is_correct=bool(o['is_correct'])) for o in options],accepted_answers=[a['value'] for a in accepted])
                    document['questions'].append(item)
                validated = validate_publication(document)
                if digest(validated) != version['content_hash']: raise ContentError('Test content hash mismatch')

    def files(self):
        def clean(row): return {k:(None if k in AUTHORS else deepcopy(v)) for k,v in row.items()}
        thematic = self.domain == 'thematic'; foreign = 'variant_id' if thematic else 'test_id'
        catalog = {'schema_version':1, 'domain':self.domain, 'counters':self.counters,
                   'catalog_state':deepcopy(self.data['thematic_catalog_state' if thematic else 'test_catalog_state'][0]),
                   'material_ids':[r['id'] for r in self.data[self.parent_table]],
                   'media':[clean(r) for r in self.data['thematic_media' if thematic else 'test_media']]}
        result = {self.root/'catalog.json': catalog}
        for row in self.data[self.parent_table]:
            ident = row['id']; folder = self.root/(('variant_' if thematic else 'test_')+str(ident))
            versions = [v for v in self.data[self.version_table] if v[foreign] == ident]
            draft = next((d for d in self.data['thematic_drafts' if thematic else 'test_drafts'] if d[foreign] == ident),None)
            material = {'schema_version':1,'material':clean(row),'draft':clean(draft) if draft else None,'version_ids':[v['id'] for v in versions]}
            if not thematic: material['media_links'] = [clean(l) for l in self.data['test_media_links'] if l['test_id']==ident]
            result[folder/'material.json'] = material
            for version in versions:
                vid = version['id']
                if thematic:
                    tables = {t:[clean(r) for r in self.data[t] if r['version_id']==vid] for t in ('thematic_version_items','thematic_item_media')}
                else:
                    questions = [r for r in self.data['test_version_questions'] if r['version_id']==vid]
                    ids = {r['id'] for r in questions}
                    tables = {'test_version_questions':[clean(r) for r in questions], **{t:[clean(r) for r in self.data[t] if r['question_id'] in ids] for t in ('test_question_options','test_accepted_answers')}}
                result[folder/'versions'/(str(vid)+'.json')] = {'schema_version':1,'version':clean(version),'tables':tables}
        return result


def store_for(db, domain):
    active = _active(db)
    if not active:
        with transaction(db):
            return store_for(db, domain)
    if domain not in active['stores']:
        store = Store(db,domain)
        active['stores'][domain] = store
        store.register()
    return active['stores'][domain]


def initialize(db, domain, tables):
    """Migration-only export: caller owns new/isolated output directory."""
    store = object.__new__(Store)
    store.db, store.domain = db, domain
    store.root = content_root(db)/('thematic_variants' if domain=='thematic' else 'tests_content')
    store.media_root = store.root/'media'
    store.data = {t:deepcopy(tables.get(t,[])) for t in TABLES[domain]}
    catalog = 'thematic_catalog_state' if domain=='thematic' else 'test_catalog_state'
    if not store.data[catalog]: store.data[catalog] = [{'singleton_id':1,'revision':1}]
    store.counters, store.original_files, store.dirty = {}, {}, False
    store.validate()
    files = store.files()
    if any(p.exists() for p in files): raise ContentError('Export destination already exists')
    for path, document in files.items(): _write(path,document)
    return store
