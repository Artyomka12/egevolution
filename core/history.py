"""Merge read-only history without changing legacy EGE aggregate meanings."""
from datetime import datetime
from features.thematic.student_views import installed, duration, percent
from core.content_store import store_for, ContentError


def merged_history(db, actor, legacy):
    result = []
    for entry in legacy:
        row = dict(entry, kind='full', title=f'Вариант №{entry["variant_num"]}', type_label='Полноценный',
                   result_url=f'/stats/attempt/{entry["id"]}', admin_result_url=f'/admin/user/{actor}/attempt/{entry["id"]}')
        row['sort_date'] = row['date']
        for pattern in ('%Y-%m-%d %H:%M:%S', '%d.%m.%Y %H:%M', '%d.%m.%Y %H:%M:%S', '%d.%m.%Y'):
            try:
                row['sort_date'] = datetime.strptime(row['date'], pattern).isoformat(sep=' ')
                break
            except ValueError:
                continue
        result.append(row)
    if installed(db):
        content = store_for(db, 'thematic')
        for record in db.execute('''SELECT a.* FROM thematic_attempts a
            WHERE a.user_id=? AND a.state='finished'
            ORDER BY a.submitted_at DESC,a.id DESC''', (actor,)):
            version = content.get('thematic_versions', record['version_id'])
            if version is None:
                raise ContentError('Historical version is unavailable')
            row = dict(record, title=version['title'], version_no=version['version_no'])
            stamp = datetime.fromtimestamp(row['submitted_at'] / 1000)
            result.append({'id': row['id'], 'kind': 'thematic', 'type_label': 'Тематический', 'title': row['title'],
                'date': stamp.strftime('%d.%m.%Y %H:%M'), 'sort_date': stamp.isoformat(sep=' '),
                'score': row['correct_count'], 'total_tasks': row['total_count'], 'percentage': percent(row['correct_count'], row['total_count']),
                'time_spent': duration(row['elapsed_ms']), 'version_no': row['version_no'],
                'result_url': f'/thematic-attempts/{row["id"]}/result',
                'admin_result_url': f'/admin/user/{actor}/thematic-attempt/{row["id"]}'})
    return sorted(result, key=lambda row: (row['sort_date'], row['kind'], row['id']), reverse=True)
