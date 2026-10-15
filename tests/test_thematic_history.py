from test_thematic_student_routes import StudentPageCase
from features.thematic import attempts


class HistoryTests(StudentPageCase):
    def test_history_keeps_legacy_aggregates_and_each_thematic_attempt(self):
        self.db.execute("INSERT INTO user_results(user_id,variant_num,score,secondary_score,total_tasks,date,time_spent) VALUES (2,1,7,30,27,'2026-01-01 10:00:00','00:10:00')")
        before = self.module.load_user_stats(2)
        one = self.complete()
        two = self.complete(2, 'second-history-key-001')
        after = self.module.load_user_stats(2)
        for field in ['total_variants', 'best_score', 'average_score', 'variants_history']:
            self.assertEqual(after[field], before[field])
        self.assertEqual(len(after['solution_history']), 3)
        self.assertEqual({r['id'] for r in after['solution_history'] if r['kind'] == 'thematic'}, {one, two})
        page = self.client.get('/stats')
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('Полноценный', page.text)
        self.assertIn('Тематический', page.text)
        self.assertIn(f'/thematic-attempts/{two}/result', page.text)
        self.actor(3)
        self.assertNotIn('Historical title', self.client.get('/stats').text)
        self.actor(1)
        self.assertIn(f'/admin/user/2/thematic-attempt/{one}', self.client.get('/admin/user/2').text)
        self.assertNotIn('Historical title', self.client.get('/admin/user/3').text)
        attempts.delete_variant(self.db, self.variant, {'confirmed': True, 'expected_revision': 1, 'request_key': 'delete-history-key-01'}, 1)
        self.assertEqual(len(self.module.load_user_stats(2)['solution_history']), 3)
