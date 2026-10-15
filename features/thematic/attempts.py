"""Server-owned thematic attempts; no Flask, live bank or client clocks."""
import json
from . import repository, service
from .grading import answer_spec, grade
from .serializers import task_dto
from .validation import canonical_json


class AttemptError(ValueError):
    def __init__(self, code, status, message, **details):
        super().__init__(message)
        self.code, self.status, self.details = code, status, details


def fail(code, status, message, **details):
    raise AttemptError(code, status, message, **details)


def available(parent):
    if parent is None:
        fail('NOT_FOUND', 404, 'Вариант не найден')
    if parent['state'] in {'deleted', 'deleting'}:
        fail('VARIANT_DELETED', 410, 'Вариант удалён')
    if parent['state'] == 'hidden':
        fail('VARIANT_HIDDEN', 423, 'Вариант временно скрыт преподавателем')
    if parent['state'] != 'published':
        fail('NOT_FOUND', 404, 'Вариант не опубликован')


def owned(db, ident, actor):
    row = db.execute('SELECT * FROM thematic_attempts WHERE id=? AND user_id=?', (ident, actor)).fetchone()
    if row is None:
        fail('NOT_FOUND', 404, 'Попытка не найдена')
    return dict(row)


def active(db, attempt):
    available(repository.row(db, 'variants', attempt['variant_id']))
    if attempt['state'] != 'active':
        fail('ATTEMPT_FINISHED', 409, 'Попытка уже завершена')


def server_time(db, variant_id):
    # Wall clock rollback must not invert already recorded events.
    times = [service.now_ms()]
    row = repository.row(db, 'variants', variant_id)
    if row:
        times.append(row['updated_at'])
    for sql in [
        'SELECT MAX(started_at) FROM thematic_attempts WHERE variant_id=?',
        'SELECT MAX(submitted_at) FROM thematic_attempts WHERE variant_id=?',
        'SELECT MAX(hidden_at) FROM thematic_visibility_intervals WHERE variant_id=?',
        'SELECT MAX(visible_at) FROM thematic_visibility_intervals WHERE variant_id=?',
        '''SELECT MAX(a.saved_at) FROM thematic_answers a JOIN thematic_attempts t ON t.id=a.attempt_id WHERE t.variant_id=?''',
        '''SELECT MAX(a.checked_at) FROM thematic_answers a JOIN thematic_attempts t ON t.id=a.attempt_id WHERE t.variant_id=?''']:
        value = db.execute(sql, (variant_id,)).fetchone()[0]
        if value is not None:
            times.append(value)
    return max(times)


def elapsed(db, attempt, end):
    start = attempt['started_at']
    blocked = sum(max(0, min(end, row['visible_at'] if row['visible_at'] is not None else end) - max(start, row['hidden_at']))
                  for row in db.execute('SELECT hidden_at,visible_at FROM thematic_visibility_intervals WHERE variant_id=?', (attempt['variant_id'],)))
    return max(0, end - start - blocked)


def summary(attempt):
    fields = ('id', 'variant_id', 'version_id', 'attempt_no', 'state', 'started_at', 'submitted_at', 'finish_reason', 'elapsed_ms', 'correct_count', 'total_count', 'result_revision')
    return {key: attempt[key] for key in fields}


def start(db, variant_id, body, actor):
    key, hashed = service.request_identity(body)
    scope = f'start:{variant_id}'
    with repository.transaction(db):
        parent = repository.row(db, 'variants', variant_id)
        available(parent)
        old = service.receipt(db, actor, scope, key, hashed)
        if old:
            return summary(owned(db, old, actor))
        existing = db.execute("SELECT id FROM thematic_attempts WHERE user_id=? AND variant_id=? AND state='active'", (actor, variant_id)).fetchone()
        now = server_time(db, variant_id)
        if existing:
            ident = existing[0]
        else:
            version = repository.get_version(db, parent['current_version_id'])
            if not version:
                raise ValueError('Отсутствует опубликованная версия')
            number = db.execute('SELECT COALESCE(MAX(attempt_no),0)+1 FROM thematic_attempts WHERE user_id=? AND variant_id=?', (actor, variant_id)).fetchone()[0]
            ident = db.execute('''INSERT INTO thematic_attempts(user_id,variant_id,version_id,attempt_no,started_at,total_count,start_request_key)
                VALUES (?,?,?,?,?,?,?)''', (actor, variant_id, version['id'], number, now, version['question_count'], f'{variant_id}:{key}')).lastrowid
            db.executemany('INSERT INTO thematic_answers(attempt_id,item_id,version_id) VALUES (?,?,?)',
                           [(ident, item['id'], version['id']) for item in version['items']])
        service.record(db, actor, scope, key, hashed, ident, now)
        return summary(owned(db, ident, actor))


def item_answer(db, attempt, item_id):
    row = db.execute('SELECT * FROM thematic_answers WHERE attempt_id=? AND item_id=?', (attempt['id'], item_id)).fetchone()
    item = repository.row(db, 'version_items', item_id)
    if row is None or item is None or item['version_id'] != row['version_id'] or item['version_id'] != attempt['version_id']:
        fail('NOT_FOUND', 404, 'Задача не принадлежит попытке')
    return dict(row), json.loads(item['snapshot_json'])


def validate_answer(snapshot, answer):
    if answer is None:
        return
    kind, ref = answer_spec(snapshot['grading'])
    valid = isinstance(answer, str) if kind == 'scalar' else (
        isinstance(answer, list) and len(answer) == 2 and all(isinstance(v, str) for v in answer)
        if kind == 'pair' else isinstance(answer, list) and len(answer) == len(ref) and all(
            isinstance(row, list) and len(row) == len(expected) and all(isinstance(v, str) for v in row)
            for row, expected in zip(answer, ref)))
    if not valid or len(canonical_json(answer)) > 100_000:
        fail('INVALID_ANSWER', 400, 'Неверный формат или размер ответа')


def save_value(db, attempt, item_id, body, now):
    row, snapshot = item_answer(db, attempt, item_id)
    expected = body.get('expected_revision')
    if type(expected) is not int or expected < 0 or 'answer' not in body:
        fail('INVALID_INPUT', 400, 'Требуются answer и expected_revision')
    if expected != row['revision']:
        fail('ANSWER_CONFLICT', 409, 'Ответ изменён другим запросом', revision=row['revision'], item_id=item_id)
    validate_answer(snapshot, body['answer'])
    revision = expected + 1
    db.execute('''UPDATE thematic_answers SET answer_json=?,revision=?,saved_at=?,checked_revision=NULL,is_correct=NULL,checked_at=NULL,final_status=NULL
        WHERE attempt_id=? AND item_id=?''', (canonical_json(body['answer']), revision, now, attempt['id'], item_id))
    return revision, snapshot


def mutate(db, ident, item_id, body, actor, *, check=False):
    identity = dict(body)
    if not check:
        identity['request_key'] = identity.pop('mutation_id', None)
    key, hashed = service.request_identity(identity)
    scope = f'{"check" if check else "save"}:{ident}:{item_id}'
    with repository.transaction(db):
        attempt = owned(db, ident, actor)
        active(db, attempt)
        old = service.receipt(db, actor, scope, key, hashed)
        row, snapshot = item_answer(db, attempt, item_id)
        if old:
            result = {'revision': (old - 1) // 2 if check else old, 'current_revision': row['revision'], 'replayed': True}
            if check:
                result['is_correct'] = bool((old - 1) % 2)
            return result
        now = server_time(db, attempt['variant_id'])
        recent = db.execute("""SELECT COUNT(*) FROM thematic_operation_keys WHERE actor_user_id=? AND created_at>? AND
            (operation_scope LIKE 'save:%' OR operation_scope LIKE 'check:%')""", (actor, now - 60_000)).fetchone()[0]
        if recent >= 240:
            fail('RATE_LIMITED', 429, 'Слишком много запросов. Повторите позже.', retry_after=60)
        if 'answer' in body or not check:
            revision, snapshot = save_value(db, attempt, item_id, body, now)
            answer = body['answer']
        else:
            if type(body.get('expected_revision')) is not int or body['expected_revision'] != row['revision']:
                fail('ANSWER_CONFLICT', 409, 'Ответ изменён', revision=row['revision'], item_id=item_id)
            revision, answer = row['revision'], json.loads(row['answer_json']) if row['answer_json'] else None
        result = {'revision': revision, 'saved_at': now, 'replayed': False}
        resource = revision
        if check:
            checked = grade(snapshot['grading'], answer, grader_version=snapshot['grader_version'])
            if checked.status == 'skipped':
                fail('EMPTY_ANSWER', 400, 'Введите ответ')
            db.execute('UPDATE thematic_answers SET checked_revision=?,is_correct=?,checked_at=? WHERE attempt_id=? AND item_id=?',
                       (revision, checked.score, now, ident, item_id))
            result['is_correct'] = bool(checked.score)
            resource = revision * 2 + checked.score + 1
        service.record(db, actor, scope, key, hashed, resource, now)
        return result


def finalize(db, attempt, now, reason):
    """Caller owns the write lock. Every stored answer is graded again."""
    version = repository.get_version(db, attempt['version_id'])
    rows = db.execute('SELECT * FROM thematic_answers WHERE attempt_id=?', (attempt['id'],)).fetchall()
    answers = {row['item_id']: row for row in rows}
    if version is None or len(answers) != attempt['total_count'] or len(version['items']) != attempt['total_count']:
        raise ValueError('Нарушена целостность попытки')
    score = 0
    for item in version['items']:
        row = answers[item['id']]
        answer = json.loads(row['answer_json']) if row['answer_json'] else None
        snapshot = item['snapshot']
        validate_answer(snapshot, answer)
        result = grade(snapshot['grading'], answer, grader_version=snapshot['grader_version'])
        score += result.score
        db.execute('UPDATE thematic_answers SET checked_revision=revision,is_correct=?,checked_at=?,final_status=? WHERE attempt_id=? AND item_id=?',
                   (result.score, now, result.status, attempt['id'], item['id']))
    db.execute("""UPDATE thematic_attempts SET state='finished',submitted_at=?,finish_reason=?,elapsed_ms=?,correct_count=?,result_revision=result_revision+1 WHERE id=?""",
               (now, reason, elapsed(db, attempt, now), score, attempt['id']))


def finish(db, ident, body, actor):
    with repository.transaction(db):
        attempt = owned(db, ident, actor)
        if attempt['state'] == 'finished':
            return summary(attempt)  # Late client packets never mutate a finished result.
        active(db, attempt)
        key, hashed = service.request_identity(body)
        package = body.get('answers', [])
        if not isinstance(package, list):
            raise ValueError('answers должен быть списком')
        seen = set()
        now = server_time(db, attempt['variant_id'])
        for entry in package:
            if not isinstance(entry, dict) or type(entry.get('item_id')) is not int or entry['item_id'] in seen:
                raise ValueError('Некорректный пакет ответов')
            seen.add(entry['item_id'])
            save_value(db, attempt, entry['item_id'], entry, now)
        finalize(db, attempt, now, 'user')
        service.record(db, actor, f'finish:{ident}', key, hashed, ident, now)
        return summary(owned(db, ident, actor))


def view(db, ident, actor):
    with repository.transaction(db):
        attempt = owned(db, ident, actor)
        if attempt['state'] == 'active':
            active(db, attempt)
        now = server_time(db, attempt['variant_id'])
        result = summary(attempt)
        result['elapsed_ms'] = attempt['elapsed_ms'] if attempt['state'] == 'finished' else elapsed(db, attempt, now)
        result['server_now'] = now
        version = repository.get_version(db, attempt['version_id'])
        result.update(title=version['title'], version_no=version['version_no'], questions=[])
        for item in version['items']:
            row, snapshot = item_answer(db, attempt, item['id'])
            task = task_dto(snapshot)  # Result/reference DTO belongs to stage 1.5.
            # Only presentation metadata, never arbitrary snapshot dictionaries.
            task['materials'] = [{'media_id': m['media_id'], 'role': m['role'], 'alt_text': m['alt_text'],
                'url': f'/thematic-attempts/{ident}/media/{m["media_id"]}',
                'after_paragraph': m['display_metadata'].get('after_paragraph')} for m in task['materials']]
            task.update(item_id=item['id'], position=item['position'], revision=row['revision'],
                        answer=json.loads(row['answer_json']) if row['answer_json'] else None,
                        is_correct=bool(row['is_correct']) if row['checked_revision'] == row['revision'] else None,
                        final_status=row['final_status'])
            result['questions'].append(task)
        return result


def delete_variant(db, ident, body, actor):
    if body.get('confirmed') is not True:
        raise ValueError('Требуется подтверждение удаления')
    key, hashed = service.request_identity(body)
    expected = service.integer(body.get('expected_revision'))
    scope = f'delete:{ident}'
    with repository.transaction(db):
        old = service.receipt(db, actor, scope, key, hashed)
        if old:
            return {'id': old, 'state': 'deleted', 'replayed': True}
        parent = repository.row(db, 'variants', ident)
        if parent is None or parent['state'] in {'deleting', 'deleted'}:
            fail('VARIANT_DELETED', 410, 'Вариант удалён')
        if parent['revision'] != expected:
            raise service.Conflict('Вариант изменён. Обновите каталог.')
        now = server_time(db, ident)
        repository.update(db, 'variants', ident, state='deleting')
        db.execute('UPDATE thematic_visibility_intervals SET visible_at=?,visible_by=? WHERE variant_id=? AND visible_at IS NULL', (now, actor, ident))
        for row in db.execute("SELECT * FROM thematic_attempts WHERE variant_id=? AND state='active'", (ident,)).fetchall():
            finalize(db, dict(row), now, 'variant_deleted')
        repository.content(db).delete('thematic_drafts', ident)
        repository.update(db, 'variants', ident, state='deleted', current_version_id=None, deleted_at=now, updated_at=now, revision=parent['revision'] + 1)
        repository.bump_catalog(db)
        service.record(db, actor, scope, key, hashed, ident, now)
        return {'id': ident, 'state': 'deleted', 'replayed': False}
