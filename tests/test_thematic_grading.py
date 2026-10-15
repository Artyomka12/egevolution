import json
from pathlib import Path
import unittest
from features.thematic.grading import grade, InvalidTask, answer_spec
from features.thematic.validation import make_snapshot, validate_sources
from features.thematic.serializers import task_dto
from features.thematic.statistics import best_attempt


class GradingTests(unittest.TestCase):
    def test_scalar_normalization_and_no_numeric_coercion(self):
        task = {'correct_answer':' Да '}
        self.assertEqual(grade(task, 'ДА').score, 1)
        self.assertEqual(grade({'correct_answer':'0'}, 0).score, 0)
        self.assertEqual(grade({'correct_answer':'01'}, '1').score, 0)
        self.assertEqual(grade({'correct_answer':'a b'}, 'ab').score, 0)
        self.assertEqual(grade(task, '   ').status, 'skipped')

    def test_pairs_and_grids_are_all_or_nothing(self):
        task = {'answers':['1','2']}
        for answer in (['1','x'], ['2','1'], ['1'], ['1','2','3'], '12', [1,2]):
            self.assertEqual(grade(task, answer).score, 0)
        self.assertEqual(grade(task, [' 1 ', '2']).score, 1)
        grid = {'id':27, 'answer_grid':{'rows':2,'cols':2,'answers':[['A','2'],['3','']]}}
        self.assertEqual(grade(grid, [[' a ','2'],['3','']]).score, 1)
        for answer in ([['A','2'],['wrong','']], [['3',''],['A','2']], ['A','2','3'], [['A','2']]):
            self.assertEqual(grade(grid, answer).score, 0)
        self.assertEqual(grade(grid, [['',''],['','']]).status, 'skipped')
        grid['id'] = 1
        self.assertEqual(grade(grid, [['A','2'],['3','']]).score, 1)

    def test_malformed_reference_never_silently_passes(self):
        for task in ({}, {'correct_answer':''}, {'answers':['1']},
                     {'correct_answer':'1','answers':['1','2']},
                     {'answer_grid':{'rows':1,'cols':2,'answers':[['1']]}}):
            with self.assertRaises(InvalidTask):
                grade(task, '')
        with self.assertRaises(InvalidTask):
            grade({'correct_answer':'1'}, '1', grader_version='future')

    def test_all_current_bank_shapes_read_only(self):
        count = 0
        root = Path(__file__).resolve().parents[1]
        for path in sorted((root/'tasks').glob('task_*/tasks.json')):
            for task in json.loads(path.read_text(encoding='utf-8'))['tasks']:
                kind, expected = answer_spec(task)
                self.assertEqual(grade(task, expected).score, 1, str(path))
                self.assertEqual(grade(task, None).score, 0)
                count += 1
        self.assertGreater(count, 0)

    def test_detached_snapshot_and_public_dto(self):
        task={'id':1,'description':['<pre>print(1)</pre>'],'correct_answer':'1',
              'images':[{'path':'image.png','after_paragraph':0,'alt':'Diagram'}]}
        with self.assertRaises(ValueError):
            make_snapshot(1, task)
        snapshot=make_snapshot(1,task,[{'source_path':'image.png','role':'condition','position':1,'media_id':7,'sha256':'a'*64}])
        task['description'][0]='changed'; task['correct_answer']='2';task['images'][0]['alt']='changed'
        self.assertEqual(snapshot['grading']['correct_answer'],'1')
        self.assertEqual(snapshot['materials'][0]['alt_text'],'Diagram')
        self.assertNotIn('source_path',snapshot['materials'][0])
        active=task_dto(snapshot)
        self.assertNotIn('grading',active)
        self.assertNotIn('reference',active)
        self.assertEqual(task_dto(snapshot,finished=True)['reference']['correct_answer'],'1')

    def test_sources_no_pedagogical_size_limit(self):
        validate_sources([{'source_task_num':1,'source_task_id':i} for i in range(1,161)])
        validate_sources([{'source_task_num':1,'source_task_id':1},{'source_task_num':2,'source_task_id':1}])
        with self.assertRaises(ValueError):
            validate_sources([{'source_task_num':1,'source_task_id':1}]*2)
        with self.assertRaises(ValueError):
            validate_sources([])

    def test_best_counts_before_percentage(self):
        def item(id,n,d):return dict(id=id,state='finished',correct_count=n,total_count=d,submitted_at=id)
        self.assertEqual(best_attempt([item(1,15,20),item(2,10,10)])['id'],1)
        self.assertEqual(best_attempt([item(1,10,20),item(2,10,10)])['id'],2)
        self.assertIsNone(best_attempt([]))
