"""Administrative thematic lifecycle. All writes are explicit transactions."""
import json
import re
import time
from . import media, repository
from .validation import canonical_json, digest, make_snapshot, validate_draft, validate_sources

Conflict = repository.Conflict


def now_ms():
    return time.time_ns() // 1_000_000


def integer(value):
    if type(value) is not int or value < 1:
        raise ValueError('Ожидается положительная целочисленная revision')
    return value


def variant(db, ident):
    row = repository.row(db, 'variants', ident)
    if row is None or row['state'] in {'deleting', 'deleted'}:
        raise LookupError('Вариант недоступен')
    return dict(row)


def draft(db, ident):
    parent = variant(db, ident)
    row = repository.row(db, 'drafts', ident)
    if row is None:
        raise LookupError('Черновик не найден')
    number = repository.row(db, 'versions', parent['current_version_id'])
    return {'id': ident, 'state': parent['state'], 'variant_revision': parent['revision'],
            'revision': row['revision'], 'version_no': number['version_no'] if number else None,
            'document': json.loads(row['document_json'])}


def catalog(db):
    ids = [r['id'] for r in sorted(repository.rows(db, 'variants'), key=lambda r: (r['sort_order'], r['id'])) if r['state'] not in {'deleting','deleted'}]
    return {'revision': repository.row(db, 'catalog_state', 1)['revision'],
            'variants': [draft(db, ident) for ident in ids]}


def clean_document(bank, document):
    validate_draft(document)
    title, description = document.get('title', ''), document.get('description', '')
    if len(title) > 200 or len(description) > 4000:
        raise ValueError('Название — до 200 символов, описание — до 4000')
    refs = []
    for item in document.get('items', []):
        number, ident = item['source_task_num'], item['source_task_id']
        task = bank.task(number, ident)
        source_hash = digest(task)
        if item.get('source_hash', source_hash) != source_hash:
            raise Conflict(f'Задача №{number}, ID {ident} изменена в банке. Удалите её из черновика и добавьте заново.')
        refs.append({'source_task_num': number, 'source_task_id': ident, 'source_hash': source_hash})
    return {'title': title, 'description': description, 'items': refs}


def request_identity(body):
    key = body.get('request_key')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', key):
        raise ValueError('Требуется ключ операции request_key (16–100 символов)')
    return key, digest(body)


def receipt(db, actor, scope, key, request_hash):
    row = db.execute('SELECT * FROM thematic_operation_keys WHERE actor_user_id=? AND operation_scope=? AND request_key=?',
                     (actor, scope, key)).fetchone()
    if row and row['request_hash'] != request_hash:
        raise Conflict('Ключ операции уже использован с другим содержимым')
    return row['resource_id'] if row else None


def record(db, actor, scope, key, request_hash, resource, now):
    db.execute('INSERT INTO thematic_operation_keys VALUES (?,?,?,?,?,?)', (actor, scope, key, request_hash, resource, now))


def create(db, bank, body, actor):
    key, request_hash = request_identity(body)
    old = receipt(db, actor, 'create', key, request_hash)
    if old:
        return draft(db, old)
    document = clean_document(bank, body.get('document'))
    with repository.transaction(db):
        old = receipt(db, actor, 'create', key, request_hash)
        if old:
            return draft(db, old)
        now = now_ms()
        ident = repository.insert(db, 'variants', dict(created_at=now, updated_at=now, created_by=actor,
            sort_order=max((r['sort_order'] for r in repository.rows(db, 'variants')), default=-1) + 1,
            state='draft', revision=1, current_version_id=None, deleted_at=None))
        repository.insert(db, 'drafts', dict(variant_id=ident, document_json=canonical_json(document), revision=1,
            updated_by=actor, updated_at=now, based_on_version_id=None))
        repository.bump_catalog(db)
        record(db, actor, 'create', key, request_hash, ident, now)
    return draft(db, ident)


def save(db, bank, ident, body, actor):
    expected = integer(body.get('expected_revision'))
    document = clean_document(bank, body.get('document'))
    repository.save_draft(db, ident, document, expected_revision=expected, actor_id=actor, now=now_ms())
    return draft(db, ident)


def publish(db, bank, media_root, ident, body, actor):
    key, request_hash = request_identity(body)
    scope = f'publish:{ident}'
    old = receipt(db, actor, scope, key, request_hash)
    if old:
        return {'version_id': old, 'replayed': True, 'draft': draft(db, ident)}
    expected = integer(body.get('expected_revision'))
    expected_variant = integer(body.get('variant_revision'))
    current = draft(db, ident)
    if current['revision'] != expected or current['variant_revision'] != expected_variant:
        old = receipt(db, actor, scope, key, request_hash)
        if old:
            return {'version_id': old, 'replayed': True, 'draft': draft(db, ident)}
        raise Conflict('Черновик или статус изменён другим администратором. Обновите страницу.')
    document = clean_document(bank, current['document'])
    if not document['title'].strip():
        raise ValueError('Перед публикацией укажите название')
    validate_sources(document['items'])
    prepared = []
    # File I/O and validation deliberately occur before the SQLite write lock.
    for ref in document['items']:
        task = bank.task(ref['source_task_num'], ref['source_task_id'])
        if digest(task) != ref['source_hash']:
            raise Conflict('Банк изменился во время подготовки публикации')
        materials = []
        for item in bank.materials(ref['source_task_num'], task):
            info = media.stage(media_root, item['path'], item['role'] == 'condition')
            materials.append((item, info))
        prepared.append((ref, task, materials))
    # Reject a changed bank or material; never silently mix two readings.
    for ref, task, materials in prepared:
        if digest(bank.task(ref['source_task_num'], ref['source_task_id'])) != ref['source_hash']:
            raise Conflict('Банк изменился во время публикации')
        for item, info in materials:
            if media.read_material(item['path'], item['role'] == 'condition')[1]['sha256'] != info['sha256']:
                raise Conflict('Материал изменился во время публикации')
    with repository.transaction(db):
        old = receipt(db, actor, scope, key, request_hash)
        if old:
            return {'version_id': old, 'replayed': True, 'draft': draft(db, ident)}
        current = draft(db, ident)
        if current['revision'] != expected or current['variant_revision'] != expected_variant:
            raise Conflict('Черновик или статус изменён во время публикации')
        from .attempts import server_time
        now = server_time(db, ident)
        snapshots = []
        for ref, task, materials in prepared:
            copied = [dict(item, media_id=media.register(db, info, now), sha256=info['sha256']) for item, info in materials]
            snapshots.append(make_snapshot(ref['source_task_num'], task, copied))
        version = repository.store_version_in_transaction(db, ident, document['title'], document['description'], snapshots, actor_id=actor, now=now)
        repository.update(db, 'variants', ident, current_version_id=version, state='published', revision=current['variant_revision'] + 1, updated_at=now)
        repository.update(db, 'drafts', ident, based_on_version_id=version, revision=current['revision'] + 1, updated_at=now, updated_by=actor)
        db.execute('UPDATE thematic_visibility_intervals SET visible_at=MAX(hidden_at,?),visible_by=? WHERE variant_id=? AND visible_at IS NULL', (now, actor, ident))
        repository.bump_catalog(db)
        record(db, actor, scope, key, request_hash, version, now)
    return {'version_id': version, 'replayed': False, 'draft': draft(db, ident)}


def visibility(db, ident, body, actor):
    expected = integer(body.get('expected_revision'))
    state = body.get('state')
    if state not in {'published', 'hidden'}:
        raise ValueError('Недопустимый статус публикации')
    with repository.transaction(db):
        current = variant(db, ident)
        if current['revision'] != expected:
            raise Conflict('Статус изменён. Обновите список.')
        if not current['current_version_id']:
            raise ValueError('Сначала опубликуйте черновик в конструкторе')
        if current['state'] != state:
            from .attempts import server_time
            now = server_time(db, ident)
            if state == 'hidden':
                db.execute('INSERT INTO thematic_visibility_intervals(variant_id,hidden_at,hidden_by) VALUES (?,?,?)', (ident, now, actor))
            else:
                db.execute('UPDATE thematic_visibility_intervals SET visible_at=MAX(hidden_at,?),visible_by=? WHERE variant_id=? AND visible_at IS NULL', (now, actor, ident))
            repository.update(db, 'variants', ident, state=state, revision=current['revision'] + 1, updated_at=now)
            repository.bump_catalog(db)
    return draft(db, ident)


def reorder(db, body):
    expected, ids = integer(body.get('expected_revision')), body.get('ids')
    if not isinstance(ids, list) or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Некорректный список вариантов')
    with repository.transaction(db):
        current = catalog(db)
        if current['revision'] != expected:
            raise Conflict('Каталог изменён. Обновите список.')
        if set(ids) != {v['id'] for v in current['variants']}:
            raise ValueError('Список должен содержать все доступные варианты')
        for position, ident in enumerate(ids):
            repository.update(db, 'variants', ident, sort_order=position)
        repository.bump_catalog(db)
    return catalog(db)
