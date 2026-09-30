"""One-time content migration: 13 -> 10, 23 -> 13, retain content at 23.

Run without --apply for an audit. Stop the web server before --apply.
Backups include the database and every replaced directory; never rerun on
already migrated content. No app import, schema changes or notifications.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path('.local-data/ege-renumber-2026.json')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    original = path.read_text(encoding='utf-8') if path.exists() else ''
    indent_match = re.search(r'\n( +)"', original)
    indent = len(indent_match[1]) if indent_match else 2
    path.write_text(json.dumps(data, ensure_ascii=False, indent=indent) + '\n', encoding='utf-8')


def remap_answers(answers):
    result = {k: v for k, v in answers.items() if k not in ('10', '13', '23')}
    for old, new in [('13', '10'), ('23', '13')]:
        if old in answers:
            result[new] = answers[old]
    return result


def migrate(root, apply=False, source_ref=None, backup_root=None):
    root = Path(root).resolve()
    database_only = source_ref is not None
    if database_only:
        if not re.fullmatch(r'[0-9a-f]{40}', source_ref):
            raise RuntimeError('Use the full, confirmed pre-update Git commit.')
        if backup_root is None:
            raise RuntimeError('Database-only migration requires an external backup directory.')
        backup_root = Path(backup_root).expanduser().resolve()
        if backup_root == root or root in backup_root.parents:
            raise RuntimeError('Server backups must be outside the website directory.')

    def source_json(relative):
        if not database_only:
            return read_json(root / relative)
        raw = subprocess.check_output(
            ['git', 'show', source_ref + ':' + Path(relative).as_posix()], cwd=str(root))
        return json.loads(raw.decode('utf-8'))

    marker = root / ARCHIVE
    if marker.exists():
        raise RuntimeError('Migration already applied; refusing to overwrite its archive.')
    bases = {n: source_json(f'tasks/task_{n:02}/tasks.json') for n in range(1, 28)}
    theories = {n: source_json(f'theory/task_{n:02}/theory.json') for n in (10, 13, 23)}
    if 'Адресация' not in theories[13]['title'] or 'Перебор' not in theories[23]['title']:
        raise RuntimeError('Unexpected source topics; content may already be renumbered.')
    if database_only:
        paths = subprocess.check_output(
            ['git', 'ls-tree', '-r', '--name-only', source_ref, '--', 'variants'], cwd=str(root)
        ).decode('utf-8').splitlines()
        paths = [Path(p) for p in paths if re.fullmatch(r'variants/variant_\d+/variant_\d+\.json', p)]
    else:
        paths = [p.relative_to(root) for p in sorted((root / 'variants').glob('variant_*/variant_*.json'))]
    variants = {p: source_json(p) for p in paths}
    if not variants:
        raise RuntimeError('No source variants found.')
    for variant in variants.values():
        if not isinstance(variant['tasks'], dict):
            raise RuntimeError('Expected reference-based variants; review legacy variants manually.')
        for n, ref in variant['tasks'].items():
            if not any(t['id'] == ref['task_id'] for t in bases[int(n)]['tasks']):
                raise RuntimeError(f'Missing task {n}/{ref["task_id"]}')
    if database_only:
        # git pull has installed the new content, but history still refers to
        # the explicitly selected old commit. Reject an unexpected release.
        for new in range(1, 28):
            expected = deepcopy(bases[{10: 13, 13: 23}.get(new, new)])
            expected['task_num'] = new
            if read_json(root / f'tasks/task_{new:02}/tasks.json') != expected:
                raise RuntimeError(f'Installed task bank {new} does not match the migration.')
        for old, new in [(13, 10), (23, 13), (23, 23)]:
            expected = deepcopy(theories[old])
            expected['task_id'] = new
            expected['theory']['description'] = [s.replace(f'Задание №{old}', f'Задание №{new}') for s in expected['theory']['description']]
            if read_json(root / f'theory/task_{new:02}/theory.json') != expected:
                raise RuntimeError(f'Installed theory {new} does not match the migration.')
        installed_paths = {p.relative_to(root) for p in (root / 'variants').glob('variant_*/variant_*.json')}
        if installed_paths != set(variants):
            raise RuntimeError('Installed variants differ from the source variant list.')
        for relative, original in variants.items():
            expected = deepcopy(original)
            expected['tasks']['10'] = deepcopy(original['tasks']['13'])
            expected['tasks']['13'] = deepcopy(original['tasks']['23'])
            if read_json(root / relative) != expected:
                raise RuntimeError(f'Installed variant does not match: {relative}')
    database = root / 'users.db'
    if not database.is_file() or database.is_symlink():
        raise RuntimeError('Existing regular users.db required; refusing to create a database.')
    report = {'old_counts': {n: len(bases[n]['tasks']) for n in (10, 13, 23)},
              'new_counts': {10: len(bases[13]['tasks']), 13: len(bases[23]['tasks']), 23: len(bases[23]['tasks'])},
              'variants': len(variants), 'database_only': database_only}
    if database_only:
        report['source_ref'] = source_ref
    if not apply:
        return report

    # A fixed, resolved workspace child: neither symlinks nor paths outside root
    # are accepted for any directory that will be moved/replaced.
    affected = [] if database_only else [Path(f'{kind}/task_{n:02}') for kind in ('tasks', 'theory') for n in (10, 13)]
    for rel in affected:
        path = root / rel
        if path.is_symlink() or path.resolve() != path.absolute() or root not in path.resolve().parents:
            raise RuntimeError(f'Unsafe replacement path: {path}')
    backup = (backup_root or root / '.local-backups') / ('ege-renumber-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True, mode=0o700)
    if database_only:
        for n, data in bases.items():
            write_json(backup / f'tasks/task_{n:02}/tasks.json', data)
        for n, data in theories.items():
            write_json(backup / f'theory/task_{n:02}/theory.json', data)
        for relative, data in variants.items():
            write_json(backup / relative, data)
    else:
        for rel in affected + [Path('tasks/task_23'), Path('theory/task_23')]:
            shutil.copytree(root / rel, backup / rel)
        shutil.copytree(root / 'variants', backup / 'variants')
    db = sqlite3.connect(str(database))
    db.row_factory = sqlite3.Row
    destination = sqlite3.connect(str(backup / 'users.db'))
    try:
        db.backup(destination)
    finally:
        destination.close()
    archive = {'migration': 'ege-renumber-2026', 'answer_id_cutoff': 0, 'attempts': {}}
    moved = []
    try:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Source database failed integrity_check.')
        preserved_tables = ('users', 'user_results', 'user_task_answers', 'user_lesson_progress')
        preserved = {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in preserved_tables}
        report['preserved_counts'] = {t: len(rows) for t, rows in preserved.items()}
        archive['answer_id_cutoff'] = db.execute('SELECT COALESCE(MAX(id), 0) FROM user_task_answers').fetchone()[0]
        # The history screen needs original correct answers and safe links to the
        # moved banks. Keep its old exam numbering and earned points intact.
        for attempt in db.execute('SELECT id, variant_num FROM user_results').fetchall():
            variant = variants[Path(f'variants/variant_{attempt["variant_num"]:02}/variant_{attempt["variant_num"]:02}.json')]
            tasks = []
            for position, ref in sorted(variant['tasks'].items(), key=lambda pair: int(pair[0])):
                number = int(position)
                task = deepcopy(next(t for t in bases[number]['tasks'] if t['id'] == ref['task_id']))
                task['id'] = number
                if number != 10:
                    task['_source_task_num'] = {13: 10, 23: 13}.get(number, number)
                    task['_base_task_id'] = ref['task_id']
                tasks.append(task)
            archive['attempts'][str(attempt['id'])] = tasks

        stage = backup / 'staged'
        for old, new in ([] if database_only else [(13, 10), (23, 13)]):
            for kind, filename, key in [('tasks', 'tasks.json', 'task_num'), ('theory', 'theory.json', 'task_id')]:
                destination = stage / kind / f'task_{new:02}'
                shutil.copytree(backup / kind / f'task_{old:02}', destination)
                data = read_json(destination / filename)
                data[key] = new
                # Only the EGE topic introduction uses the exam number. Practice
                # titles like "Задание 13" are exercise indices, not exam topics.
                if kind == 'theory':
                    data['theory']['description'] = [s.replace(f'Задание №{old}', f'Задание №{new}') for s in data['theory']['description']]
                write_json(destination / filename, data)

        for rel in affected:
            original = backup / 'original-directories' / rel
            original.parent.mkdir(parents=True, exist_ok=True)
            (root / rel).rename(original)
            moved.append(rel)
            (stage / rel).rename(root / rel)
        for rel, variant in ([] if database_only else variants.items()):
            updated = deepcopy(variant)
            updated['tasks']['10'] = deepcopy(variant['tasks']['13'])
            updated['tasks']['13'] = deepcopy(variant['tasks']['23'])
            write_json(root / rel, updated)

        for table in ('user_theory_progress', 'user_theory_last_answer', 'user_theory_access'):
            db.execute(f'DELETE FROM {table} WHERE task_num=10')
            db.execute(f'UPDATE {table} SET task_num=10 WHERE task_num=13')
            db.execute(f'UPDATE {table} SET task_num=13 WHERE task_num=23')
        # Retain access to the temporary duplicate without duplicating attempts.
        db.execute('INSERT INTO user_theory_access (user_id, task_num, is_unlocked) SELECT user_id, 23, is_unlocked FROM user_theory_access WHERE task_num=13')
        db.execute('DELETE FROM task_usage WHERE task_num=10')
        db.execute('UPDATE task_usage SET task_num=10 WHERE task_num=13')
        db.execute('INSERT INTO task_usage (task_num, task_id, variant_num, used_at) SELECT 13, task_id, variant_num, used_at FROM task_usage WHERE task_num=23')
        for row in db.execute('SELECT id, answers_json FROM user_variant_progress').fetchall():
            answers = remap_answers(json.loads(row['answers_json']))
            db.execute('UPDATE user_variant_progress SET answers_json=? WHERE id=?', (json.dumps(answers, ensure_ascii=False), row['id']))
        for table, rows in preserved.items():
            if [tuple(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] != rows:
                raise RuntimeError(f'Unexpected change to preserved table: {table}')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Migrated database failed integrity_check.')
        report['theory_progress_after'] = db.execute('SELECT COUNT(*) FROM user_theory_progress').fetchone()[0]
        write_json(marker, archive)
        db.commit()
    except Exception:
        db.rollback()
        for rel in reversed(moved):
            if (root / rel).exists():
                failed = backup / 'failed' / rel
                failed.parent.mkdir(parents=True, exist_ok=True)
                (root / rel).rename(failed)
            (backup / 'original-directories' / rel).rename(root / rel)
        for rel in ([] if database_only else variants):
            shutil.copy2(backup / rel, root / rel)
        marker.unlink(missing_ok=True)
        raise
    finally:
        db.close()
    report.update(backup=str(backup), archived_attempts=len(archive['attempts']))
    write_json(backup / 'report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--source-ref', help='Server mode: read old content from this Git commit; change only the DB and history archive.')
    parser.add_argument('--backup-dir', type=Path, help='Private directory outside the website (required with --source-ref).')
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(migrate(ROOT, args.apply, args.source_ref, args.backup_dir), ensure_ascii=False, indent=2))
