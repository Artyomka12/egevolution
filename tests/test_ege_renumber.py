"""Exercise the destructive migration and historical results on disposable data."""
import importlib.util
import json
import hashlib
from pathlib import Path
import unittest
import tempfile
from unittest import mock
import test_homepage_integration as homepage

spec = importlib.util.spec_from_file_location('renumber', homepage.ROOT / 'scripts/renumber_ege_tasks.py')
renumber = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renumber)


class RenumberTests(unittest.TestCase):
    def setUp(self):
        homepage.HomepageIntegration.setUpClass()
        self.h = homepage.HomepageIntegration
        self.addCleanup(self.h.tearDownClass)
        self.root = Path(self.h.sandbox).resolve()
        self.app = self.h.module
        self.app.EGE_RENUMBER_ARCHIVE = str(self.root / renumber.ARCHIVE)
        self.app.TASKS_FOLDER = str(self.root / 'tasks')
        self.app.VARIANTS_FOLDER = str(self.root / 'variants')
        for n in range(1, 28):
            renumber.write_json(self.root / f'tasks/task_{n:02}/tasks.json', {
                'task_num': n, 'tasks': [{'id': n + 100, 'description': [f'original {n}'],
                                        'correct_answer': str(n * 10), 'images': [], 'file': None}]})
        for n, title in [(10, 'Поиск слов'), (13, 'Адресация'), (23, 'Перебор')]:
            renumber.write_json(self.root / f'theory/task_{n:02}/theory.json', {
                'task_id': n, 'title': title, 'theory': {'description': [f'Задание №{n}']},
                'practice': {'tasks': [{'id': 13, 'title': 'Задание 13', 'correct_answer': str(n)}]}})
        self.variant_path = self.root / 'variants/variant_01/variant_01.json'
        renumber.write_json(self.variant_path, {'format': 'references', 'tasks': {str(n): {'task_id': n + 100} for n in range(1, 28)}})
        self.original_variant = renumber.read_json(self.variant_path)
        self.original23 = (self.root / 'tasks/task_23/tasks.json').read_bytes()
        image_path = self.root / 'tasks/task_13/images/table.png'
        image_path.parent.mkdir()
        image_path.write_bytes(b'fixture image')
        db = self.app.get_db()
        for n in (10, 13, 23):
            db.execute('INSERT INTO user_theory_progress (user_id,task_num,practice_task_id,attempts,is_correct) VALUES (?,?,1,?,1)', (self.h.student_id, n, n))
            db.execute('INSERT INTO user_theory_last_answer (user_id,task_num,practice_task_id,answer_json) VALUES (?,?,1,?)', (self.h.student_id, n, json.dumps(str(n))))
            db.execute('INSERT INTO user_theory_access (user_id,task_num,is_unlocked) VALUES (?,?,1)', (self.h.student_id, n))
            db.execute('INSERT INTO user_task_answers (user_id,variant_num,task_id,user_answer,is_correct,points,attempt_date) VALUES (?,1,?,?,1,1,?)', (self.h.student_id, n, json.dumps(str(n*10)), '2026-09-24'))
            db.execute('INSERT INTO task_usage (task_num,task_id,variant_num) VALUES (?,?,1)', (n, n+100))
        db.execute('INSERT INTO user_variant_progress (user_id,variant_num,answers_json,time_remaining) VALUES (?,1,?,123)', (self.h.student_id, json.dumps({'10': 'old text', '13': 'network', '23': 'program'})))
        db.commit()
        db.close()

    def test_dry_run_does_not_change_content_or_database(self):
        before = self.h.database.read_bytes()
        self.assertEqual(renumber.migrate(self.root)['variants'], 1)
        self.assertEqual(self.h.database.read_bytes(), before)
        self.assertEqual(renumber.read_json(self.variant_path), self.original_variant)
        self.assertFalse((self.root / '.local-backups').exists())

    def test_content_history_progress_and_new_attempts(self):
        report = renumber.migrate(self.root, apply=True)
        self.assertTrue((Path(report['backup']) / 'users.db').exists())
        self.assertEqual((self.root / 'tasks/task_23/tasks.json').read_bytes(), self.original23)
        self.assertEqual((self.root / 'tasks/task_10/images/table.png').read_bytes(), b'fixture image')
        for new, old in [(10, 13), (13, 23), (23, 23)]:
            self.assertEqual(self.app.load_task_base(new)['tasks'][0]['correct_answer'], str(old*10))
            theory = renumber.read_json(self.root / f'theory/task_{new:02}/theory.json')
            self.assertEqual(theory['task_id'], new)
            self.assertEqual(theory['practice']['tasks'][0]['title'], 'Задание 13')
        tasks = {t['id']: t for t in self.app.load_tasks(1)}
        self.assertEqual(len(tasks), 27)
        self.assertEqual([tasks[n]['correct_answer'] for n in (10, 13, 23)], ['130', '230', '230'])
        detail = self.app.get_attempt_details(self.h.student_id, 1)
        archived = {t['task_data']['id']: t['task_data'] for t in detail['tasks']}
        self.assertTrue(detail['archived'])
        self.assertEqual([archived[n]['correct_answer'] for n in (10,13,23)], ['100','130','230'])
        self.assertNotIn('_base_task_id', archived[10])
        self.assertEqual(archived[13]['_source_task_num'], 10)
        self.assertIsNone(self.app.get_attempt_details(self.h.student_id + 999, 1))
        stats = {s['task_num']: s for s in self.app.load_task_number_stats(self.h.student_id)}
        self.assertEqual([stats[n]['total'] for n in (10,13,23)], [2,2,0])
        db = self.app.get_db()
        self.assertEqual([tuple(r) for r in db.execute('SELECT task_num,attempts FROM user_theory_progress WHERE task_num IN (10,13,23) ORDER BY task_num')], [(10,13),(13,23)])
        self.assertEqual(json.loads(db.execute('SELECT answers_json FROM user_variant_progress').fetchone()[0]), {'10':'network','13':'program'})
        self.assertEqual(db.execute('SELECT score FROM user_results WHERE id=1').fetchone()[0], 20)
        db.close()
        self.app.save_user_result(self.h.student_id, 1, 3, 20, '00:01:00', answers_dict={'10':'130','13':'230','23':'230'})
        stats = {s['task_num']: s for s in self.app.load_task_number_stats(self.h.student_id)}
        self.assertEqual([stats[n]['total'] for n in (10,13,23)], [3,3,1])
        self.assertFalse(self.app.get_attempt_details(self.h.student_id, 2)['archived'])
        with self.assertRaisesRegex(RuntimeError, 'already applied'):
            renumber.migrate(self.root, apply=True)

    def test_failure_restores_directories_variants_and_database(self):
        original10 = (self.root / 'tasks/task_10/tasks.json').read_bytes()
        write = renumber.write_json
        def fail_archive(path, data):
            if path == self.root / renumber.ARCHIVE:
                raise OSError('simulated disk error')
            write(path, data)
        with mock.patch.object(renumber, 'write_json', side_effect=fail_archive):
            with self.assertRaisesRegex(OSError, 'simulated'):
                renumber.migrate(self.root, apply=True)
        self.assertEqual((self.root / 'tasks/task_10/tasks.json').read_bytes(), original10)
        self.assertEqual(renumber.read_json(self.variant_path), self.original_variant)
        self.assertFalse((self.root / renumber.ARCHIVE).exists())
        db = self.app.get_db()
        self.assertEqual(db.execute('SELECT attempts FROM user_theory_progress WHERE task_num=10').fetchone()[0], 10)
        db.close()

    def prepare_server_mode(self):
        originals = {p.relative_to(self.root).as_posix(): p.read_bytes()
                     for kind in ('tasks', 'theory', 'variants')
                     for p in (self.root / kind).rglob('*.json')}
        report = renumber.migrate(self.root, apply=True)
        self.h.database.write_bytes((Path(report['backup']) / 'users.db').read_bytes())
        (self.root / renumber.ARCHIVE).unlink()
        external = Path(self.h.stack.enter_context(tempfile.TemporaryDirectory(prefix='ege-server-backups-'))).resolve()
        def git_output(args, **kwargs):
            if args[1] == 'show':
                return originals[args[2].split(':', 1)[1]]
            if args[1] == 'ls-tree':
                return '\n'.join(p for p in originals if p.startswith('variants/')).encode()
            raise AssertionError(args)
        self.h.stack.enter_context(mock.patch.object(renumber.subprocess, 'check_output', side_effect=git_output))
        return external

    def content_hashes(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for kind in ('tasks', 'theory', 'variants')
                for p in (self.root / kind).rglob('*') if p.is_file()}

    def test_server_mode_changes_only_database_and_archive(self):
        external = self.prepare_server_mode()
        before = self.content_hashes()
        database_before = self.h.database.read_bytes()
        db = self.app.get_db()
        original_dump = list(db.iterdump())
        db.close()
        audit = renumber.migrate(self.root, source_ref='a' * 40, backup_root=external)
        self.assertTrue(audit['database_only'])
        self.assertEqual(self.h.database.read_bytes(), database_before)
        report = renumber.migrate(self.root, True, 'a' * 40, external)
        self.assertEqual(self.content_hashes(), before)
        self.assertEqual(Path(report['backup']).parent, external)
        backup_db = renumber.sqlite3.connect(str(Path(report['backup']) / 'users.db'))
        self.assertEqual(list(backup_db.iterdump()), original_dump)
        backup_db.close()
        db = self.app.get_db()
        self.assertEqual([tuple(r) for r in db.execute('SELECT task_num,attempts FROM user_theory_progress WHERE task_num IN (10,13,23) ORDER BY task_num')], [(10,13),(13,23)])
        self.assertEqual(db.execute('SELECT score FROM user_results WHERE id=1').fetchone()[0], 20)
        db.close()
        self.assertTrue(self.app.get_attempt_details(self.h.student_id, 1)['archived'])
        with self.assertRaisesRegex(RuntimeError, 'already applied'):
            renumber.migrate(self.root, True, 'a' * 40, external)

    def test_server_failure_rolls_back_database_without_touching_content(self):
        external = self.prepare_server_mode()
        before = self.content_hashes()
        write = renumber.write_json
        def fail_archive(path, data):
            if path == self.root / renumber.ARCHIVE:
                raise OSError('simulated archive failure')
            write(path, data)
        with mock.patch.object(renumber, 'write_json', side_effect=fail_archive):
            with self.assertRaisesRegex(OSError, 'simulated'):
                renumber.migrate(self.root, True, 'a' * 40, external)
        self.assertEqual(self.content_hashes(), before)
        self.assertFalse((self.root / renumber.ARCHIVE).exists())
        db = self.app.get_db()
        self.assertEqual(db.execute('SELECT attempts FROM user_theory_progress WHERE task_num=10').fetchone()[0], 10)
        db.close()

    def test_server_rejects_unexpected_content_and_in_site_backups(self):
        external = self.prepare_server_mode()
        before = self.h.database.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'outside'):
            renumber.migrate(self.root, True, 'a' * 40, self.root / 'backup')
        renumber.write_json(self.root / 'tasks/task_10/tasks.json', {'task_num': 10, 'tasks': []})
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            renumber.migrate(self.root, True, 'a' * 40, external)
        self.assertEqual(self.h.database.read_bytes(), before)
        self.assertEqual(list(external.iterdir()), [])

    def test_missing_database_is_not_created(self):
        self.h.database.unlink()
        with self.assertRaisesRegex(RuntimeError, 'Existing regular users.db'):
            renumber.migrate(self.root, True)
        self.assertFalse(self.h.database.exists())


if __name__ == '__main__':
    unittest.main()
