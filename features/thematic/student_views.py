"""Read models for catalog, frozen results and solution history."""
import json
from . import attempts, repository
from .bank import condition_html
from .grading import _unanswered
from .statistics import best_attempt


def installed(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='thematic_attempts'").fetchone() is not None


def duration(milliseconds):
    seconds = milliseconds // 1000
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


def percent(score, total):
    return round(score * 100 / total, 1)


def catalog(db, actor):
    if not installed(db):
        return []
    result = []
    for parent in sorted(repository.rows(db, 'variants'), key=lambda r: (r['sort_order'], r['id'])):
        if parent['state'] != 'published':
            continue
        version = repository.row(db, 'versions', parent['current_version_id'])
        if not version or version['sealed'] != 1:
            continue
        card = {key: version[key] for key in ('title', 'description', 'question_count', 'version_no')}
        card['id'] = parent['id']
        history = repository.list_attempts(db, actor, card['id'])
        active = next((a for a in history if a['state'] == 'active'), None)
        best = best_attempt(history)
        card['best'] = dict(id=best['id'], score=best['correct_count'], total=best['total_count'], percent=percent(best['correct_count'], best['total_count'])) if best else None
        card['active'] = None
        if active:
            answered = sum(not _unanswered(json.loads(a[0]) if a[0] else None) for a in db.execute('SELECT answer_json FROM thematic_answers WHERE attempt_id=?', (active['id'],)))
            number = repository.row(db, 'versions', active['version_id'])['version_no']
            card['active'] = {'id': active['id'], 'answered': answered, 'total': active['total_count'], 'version_no': number,
                              'percent': percent(answered, active['total_count'])}
        card['status'] = 'В процессе' if active else 'Пройден' if best else 'Не начат'
        card['url'] = f'/thematic-variants/{card["id"]}/solve' if active or not best else f'/thematic-attempts/{best["id"]}/result'
        result.append(card)
    return result


def present_question(question):
    question['description_html'] = [condition_html(p) for p in question.pop('description')]
    return question


def finished_result(db, ident, actor, *, admin=False):
    with repository.transaction(db):
        attempt = attempts.owned(db, ident, actor)
        if attempt['state'] != 'finished':
            attempts.fail('ATTEMPT_ACTIVE', 409, 'Попытка ещё не завершена')
        version = repository.get_version(db, attempt['version_id'])
        parent = repository.row(db, 'variants', attempt['variant_id'])
        result = attempts.summary(attempt)
        result.update(title=version['title'], version_no=version['version_no'], percent=percent(attempt['correct_count'], attempt['total_count']),
                      duration=duration(attempt['elapsed_ms']), can_restart=parent['state'] == 'published' and not admin, questions=[])
        for item in version['items']:
            row, snapshot = attempts.item_answer(db, attempt, item['id'])
            grading = snapshot['grading']
            reference = grading.get('correct_answer', grading.get('answers', grading.get('answer_grid', {}).get('answers')))
            materials = []
            for material in snapshot['materials']:
                mid = material['media_id']
                url = f'/api/admin/thematic-variants/{attempt["variant_id"]}/media/{mid}' if admin else f'/thematic-attempts/{ident}/media/{mid}'
                materials.append({'url': url, 'role': material['role'], 'alt_text': material['alt_text'], 'after_paragraph': material['display_metadata'].get('after_paragraph')})
            result['questions'].append({'item_id': item['id'], 'position': item['position'], 'source_task_num': item['source_task_num'],
                'title': snapshot['title'], 'description_html': [condition_html(p) for p in snapshot['description']], 'materials': materials,
                'answer': json.loads(row['answer_json']) if row['answer_json'] else None, 'reference': reference,
                'status': row['final_status'], 'score': row['is_correct']})
        return result


def answer_text(value):
    if value is None or value == '':
        return '—'
    if isinstance(value, list):
        return '\n'.join(' | '.join(row) if isinstance(row, list) else row for row in value)
    return str(value)
