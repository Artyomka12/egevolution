from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier
from test_thematic_attempts import AttemptCase
from features.thematic import attempts, repository, service


class ConcurrencyTests(AttemptCase):
    def race(self, *operations):
        barrier = Barrier(len(operations))
        def run(operation):
            with closing(repository.connect(self.path)) as db:
                barrier.wait(timeout=5)
                try:
                    return operation(db)
                except attempts.AttemptError as error:
                    return error.code
        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            jobs = [pool.submit(run, operation) for operation in operations]
            return [job.result(timeout=15) for job in jobs]

    def test_two_starts_and_two_saves(self):
        results = self.race(*[lambda db, n=n: attempts.start(db, self.variant, {'request_key': f'parallel-start-{n:04}'}, 2) for n in range(2)])
        self.assertEqual(results[0]['id'], results[1]['id'])
        ident = results[0]['id']
        results = self.race(*[lambda db, n=n: attempts.mutate(db, ident, self.items[0], {
            'answer': str(n), 'expected_revision': 0, 'mutation_id': f'parallel-save-{n:04}'}, 2) for n in range(2)])
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertIn('ANSWER_CONFLICT', results)

    def test_save_against_finish(self):
        ident = self.start()['id']
        saved, final = self.race(
            lambda db: attempts.mutate(db, ident, self.items[0], {'answer': '9', 'expected_revision': 0, 'mutation_id': 'racing-save-00001'}, 2),
            lambda db: attempts.finish(db, ident, {'request_key': 'racing-finish-001'}, 2))
        self.assertEqual(final['correct_count'], 1 if isinstance(saved, dict) else 0)
        self.assertIn(saved if isinstance(saved, str) else 'ok', ['ATTEMPT_FINISHED', 'ok'])

    def test_save_against_hide(self):
        ident = self.start()['id']
        saved, _ = self.race(
            lambda db: attempts.mutate(db, ident, self.items[0], {'answer': '9', 'expected_revision': 0, 'mutation_id': 'racing-save-00001'}, 2),
            lambda db: service.visibility(db, self.variant, {'expected_revision': 1, 'state': 'hidden'}, 1))
        revision = self.db.execute('SELECT revision FROM thematic_answers WHERE attempt_id=? AND item_id=?', (ident, self.items[0])).fetchone()[0]
        self.assertEqual(revision, 1 if isinstance(saved, dict) else 0)
        if isinstance(saved, str):
            self.assertEqual(saved, 'VARIANT_HIDDEN')

    def test_save_against_delete(self):
        ident = self.start()['id']
        saved, _ = self.race(
            lambda db: attempts.mutate(db, ident, self.items[0], {'answer': '9', 'expected_revision': 0, 'mutation_id': 'racing-save-00001'}, 2),
            lambda db: attempts.delete_variant(db, self.variant, {'confirmed': True, 'expected_revision': 1, 'request_key': 'racing-delete-001'}, 1))
        final = self.finish(ident)
        self.assertEqual(final['correct_count'], 1 if isinstance(saved, dict) else 0)
        if isinstance(saved, str):
            self.assertEqual(saved, 'VARIANT_DELETED')

    def test_publication_prepared_before_delete_cannot_restore_variant(self):
        from threading import Event
        from features.thematic.bank import Bank
        from features.thematic.validation import canonical_json
        import json
        bank_root = self.root / 'bank'
        folder = bank_root / 'task_01'
        folder.mkdir(parents=True)
        (folder / 'tasks.json').write_text(json.dumps({'tasks': [{'id': 1, 'description': ['fixture'], 'correct_answer': '9'}]}), encoding='utf-8')
        self.update_content(self.db, 'drafts', self.variant,
                        document_json=canonical_json({'title': 'Prepared publication', 'items': [{'source_task_num': 1, 'source_task_id': 1}]}))
        started, resume = Event(), Event()
        class PausedBank(Bank):
            def task(bank, number, ident):
                started.set()
                if not resume.wait(5):
                    raise RuntimeError('test timeout')
                return super().task(number, ident)
        def publish():
            with closing(repository.connect(self.path)) as db:
                try:
                    service.publish(db, PausedBank(bank_root), self.root / 'media', self.variant,
                                    {'expected_revision': 1, 'variant_revision': 1, 'request_key': 'publish-delete-race'}, 1)
                except LookupError:
                    return 'deleted'
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(publish)
            try:
                self.assertTrue(started.wait(5))
                self.delete()
            finally:
                resume.set()
            self.assertEqual(future.result(timeout=10), 'deleted')
        self.assertEqual(repository.row(self.db, 'variants', self.variant)['state'], 'deleted')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM thematic_versions').fetchone()[0], 1)
