from test_thematic_attempts import AttemptCase
from features.thematic import attempts


class VisibilityTests(AttemptCase):
    def test_multiple_intervals_breaks_and_frozen_time(self):
        ident = self.start()['id']  # t=1000
        self.clock.return_value = 5000
        self.state('hidden')
        for operation in [lambda: self.start('hidden-start-key-001'), lambda: self.save(ident),
                          lambda: self.finish(ident), lambda: attempts.view(self.db, ident, 2)]:
            with self.assertRaises(attempts.AttemptError) as error:
                operation()
            self.assertEqual(error.exception.status, 423)
        self.clock.return_value = 9000
        self.state('published')
        self.clock.return_value = 11000
        self.state('hidden')
        self.clock.return_value = 14000
        self.state('published')
        self.clock.return_value = 24000  # Includes an ordinary offline break.
        self.assertEqual(attempts.view(self.db, ident, 2)['elapsed_ms'], 16000)
        final = self.finish(ident)
        self.assertEqual(final['elapsed_ms'], 16000)
        self.clock.return_value = 30000
        self.state('hidden')
        self.assertEqual(attempts.view(self.db, ident, 2)['elapsed_ms'], 16000)

    def test_delete_while_hidden_and_clock_rollback(self):
        ident = self.start()['id']
        self.clock.return_value = 4000
        self.state('hidden')
        self.clock.return_value = 2000
        self.state('published')  # Clamped to last event.
        self.clock.return_value = 6000
        self.state('hidden')
        self.clock.return_value = 20000
        self.delete()
        final = self.finish(ident)
        self.assertEqual(final['elapsed_ms'], 5000)
        self.assertEqual(final['submitted_at'], 20000)
        self.assertEqual(final['finish_reason'], 'variant_deleted')

    def test_intervals_before_start_do_not_subtract(self):
        self.state('hidden')
        self.clock.return_value = 10000
        self.state('published')
        ident = self.start()['id']
        self.clock.return_value = 13000
        self.assertEqual(self.finish(ident)['elapsed_ms'], 3000)
