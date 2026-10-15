from unittest import mock
from test_thematic_attempts import AttemptCase
from features.thematic import attempts, repository, service


class DeleteTests(AttemptCase):
    def test_all_active_finalized_history_retained(self):
        first = self.start()['id']
        second = self.start(actor=3)['id']
        self.save(first)
        self.save(second, 'wrong', actor=3)
        before = repository.get_version(self.db, self.version)
        self.clock.return_value = 7000
        self.delete()
        self.assertEqual(self.finish(first)['correct_count'], 1)
        self.assertEqual(self.finish(second, actor=3)['correct_count'], 0)
        self.assertEqual(repository.get_version(self.db, self.version), before)
        self.assertEqual(service.catalog(self.db)['variants'], [])
        self.assertEqual(repository.rows(self.db, 'drafts'), [])
        with self.assertRaises(LookupError):
            service.draft(self.db, self.variant)
        with self.assertRaises(attempts.AttemptError) as error:
            self.save(first)
        self.assertEqual(error.exception.status, 410)
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_mid_finalization_failure_rolls_back_everything(self):
        first = self.start()['id']
        self.start(actor=3)
        self.state('hidden')
        before = '\n'.join(self.db.iterdump())
        original = attempts.finalize
        count = 0
        def failing(*args):
            nonlocal count
            count += 1
            original(*args)
            if count == 2:
                raise ValueError('injected late failure')
        with mock.patch.object(attempts, 'finalize', side_effect=failing):
            with self.assertRaises(ValueError):
                self.delete()
        self.assertEqual('\n'.join(self.db.iterdump()), before)
        self.assertEqual(attempts.owned(self.db, first, 2)['state'], 'active')
