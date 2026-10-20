import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import create_app, get_db
from importer import import_rows


class DrillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {'TESTING': True, 'DATABASE': str(Path(self.tmp.name)/'test.db'),
                       'SECRET_KEY': 'drill-test', 'SEED': False}
        self.app = create_app(self.config)
        self.client, self.other = self.app.test_client(), self.app.test_client()
        self.client.post('/register', data={'username':'drill-user','password':'pass1234'})
        self.other.post('/register', data={'username':'other-user','password':'pass1234'})
        with self.app.app_context():
            rows = [{'type':kind,'stem':f'题目 {kind} {i}','options':['甲','乙','丙'],
                     'answer':'AB' if kind=='multi' else 'A','explanation':f'解析 {kind} {i}'}
                    for kind,n in [('single',4),('multi',2),('judge',2)] for i in range(n)]
            import_rows(get_db(),rows)
            self.ids = [r[0] for r in get_db().execute('SELECT id FROM questions ORDER BY id')]

    def start(self, mode='all', client=None):
        response = (client or self.client).post('/api/drill/start',json={'mode':mode})
        self.assertEqual(response.status_code,200,response.data)
        return response.json['round']

    def state(self, mode='all', client=None):
        response=(client or self.client).get('/api/drill/current?mode='+mode)
        self.assertEqual(response.status_code,200,response.data)
        return response.json['round']

    def correct(self, question):
        with self.app.app_context():
            return json.loads(get_db().execute('SELECT answer FROM questions WHERE id=?',(question['id'],)).fetchone()[0])

    def submit(self, state, correct=True, client=None):
        answer=self.correct(state['question']) if correct else ['C']
        response=(client or self.client).post(f"/api/drill/{state['id']}/answer",
                     json={'index':state['current_position'],'answer':answer})
        self.assertEqual(response.status_code,200,response.data)
        return response.json['round']

    def advance(self, state):
        response=self.client.post(f"/api/drill/{state['id']}/next",json={'index':state['current_position']})
        self.assertEqual(response.status_code,200,response.data)
        return response.json['round']

    def test_round_is_shuffled_once_and_covers_every_question_exactly_once(self):
        with patch('random.shuffle',side_effect=lambda items:items.reverse()):
            state=self.start()
        seen=[]
        while True:
            question=state['question'];seen.append(question['id'])
            self.assertNotIn('correct',question)
            self.assertNotIn('explanation',question)
            self.assertEqual(self.state()['question']['id'],question['id'])
            state=self.submit(state)
            self.assertTrue(state['question']['is_correct'])
            self.assertEqual(state['question']['correct'],self.correct(question))
            self.assertTrue(state['question']['explanation'])
            if state['finished']:break
            state=self.advance(state)
        self.assertEqual(seen,list(reversed(self.ids)))
        self.assertEqual(state['answered_count'],8)
        self.assertEqual(state['correct_count'],8)
        second=self.start()
        self.assertNotEqual(second['id'],state['id'])
        self.assertEqual(second['round_number'],2)
        self.assertEqual(second['answered_count'],0)

    def test_question_draft_and_answer_review_survive_new_app_and_login(self):
        state=self.start()
        response=self.client.post(f"/api/drill/{state['id']}/draft",json={'index':0,'answer':['B']})
        self.assertEqual(response.status_code,200,response.data)
        new_app=create_app(self.config)
        resumed=new_app.test_client()
        resumed.post('/login',data={'username':'drill-user','password':'pass1234'})
        state=self.state(client=resumed)
        self.assertEqual(state['question']['selected'],['B'])
        self.assertFalse(state['question']['submitted'])
        state=self.submit(state,False,resumed)
        again=create_app(self.config).test_client()
        again.post('/login',data={'username':'drill-user','password':'pass1234'})
        restored=self.state(client=again)
        self.assertTrue(restored['question']['submitted'])
        self.assertEqual(restored['question']['selected'],['C'])
        self.assertEqual(restored['question']['correct'],self.correct(state['question']))
        self.assertEqual(restored['answered_count'],1)

    def test_wrong_history_is_preserved_after_mastery_and_reactivated_on_new_error(self):
        all_round=self.start();qid=all_round['question']['id']
        self.submit(all_round,False)
        wrongs=self.client.get('/api/drill/wrongs').json
        self.assertEqual(wrongs['total'],1)
        self.assertEqual(wrongs['items'][0]['wrong_count'],1)
        self.assertEqual(wrongs['items'][0]['last_wrong_answer'],['C'])
        self.assertIn('correct',wrongs['items'][0])
        wrong_round=self.start('wrong')
        self.assertEqual(wrong_round['question']['id'],qid)
        self.assertTrue(self.submit(wrong_round)['finished'])
        self.assertEqual(self.client.get('/api/drill/wrongs').json['total'],0)
        history=self.client.get('/api/drill/wrongs?status=all').json
        self.assertEqual(history['total'],1)
        self.assertEqual(history['items'][0]['wrong_count'],1)
        self.assertIsNotNone(history['items'][0]['mastered_at'])
        # A later round can make the same question active again.
        with self.app.app_context():
            get_db().execute('UPDATE drill_rounds SET finished_at=1 WHERE id=?',(all_round['id'],));get_db().commit()
        with patch('random.shuffle',side_effect=lambda items:items.sort(key=lambda value:value!=qid)):
            later=self.start()
        self.submit(later,False)
        active=self.client.get('/api/drill/wrongs').json
        self.assertEqual(active['items'][0]['wrong_count'],2)
        self.assertIsNone(active['items'][0]['mastered_at'])

    def test_answer_is_immutable_and_duplicate_submission_does_not_duplicate_wrong_count(self):
        state=self.start();self.submit(state,False)
        repeated=self.client.post(f"/api/drill/{state['id']}/answer",json={'index':0,'answer':['C']})
        self.assertEqual(repeated.status_code,200)
        changed=self.client.post(f"/api/drill/{state['id']}/answer",json={'index':0,'answer':['A']})
        self.assertEqual(changed.status_code,409)
        late_draft=self.client.post(f"/api/drill/{state['id']}/draft",json={'index':0,'answer':['B']})
        self.assertEqual(late_draft.status_code,409)
        self.assertEqual(self.client.get('/api/drill/wrongs').json['items'][0]['wrong_count'],1)

    def test_cannot_skip_or_submit_future_question_or_invalid_answers(self):
        state=self.start();prefix=f"/api/drill/{state['id']}"
        self.assertEqual(self.client.post(prefix+'/next',json={'index':0}).status_code,400)
        for payload in ({'index':1,'answer':['A']},{'index':True,'answer':['A']},
                        {'index':0,'answer':[]},{'index':0,'answer':['Z']},
                        {'index':0,'answer':['A','A']},[],None):
            self.assertIn(self.client.post(prefix+'/answer',json=payload).status_code,(400,409))
        self.assertEqual(self.state()['answered_count'],0)
        self.assertEqual(self.state()['current_position'],0)

    def test_accounts_are_isolated_and_api_requires_login(self):
        state=self.start();self.submit(state,False)
        for suffix in ('draft','answer','next'):
            response=self.other.post(f"/api/drill/{state['id']}/{suffix}",json={'index':0,'answer':['C']})
            self.assertEqual(response.status_code,403,response.data)
        self.assertIsNone(self.state(client=self.other))
        self.assertEqual(self.other.get('/api/drill/wrongs?status=all').json['total'],0)
        self.assertEqual(self.app.test_client().get('/api/drill/current').status_code,401)
        self.assertEqual(self.app.test_client().post('/api/drill/start',json={'mode':'all'}).status_code,401)

    def test_resuming_start_does_not_reset_round_and_wrong_review_is_independent(self):
        state=self.start();self.submit(state,False)
        again=self.start()
        self.assertEqual(again['id'],state['id'])
        self.assertEqual(again['answered_count'],1)
        wrong=self.start('wrong')
        self.assertNotEqual(wrong['id'],state['id'])
        self.submit(wrong)
        self.assertEqual(self.state()['id'],state['id'])
        self.assertEqual(self.state()['current_position'],0)

    def test_imported_questions_enter_next_round_without_disrupting_current_round(self):
        state=self.start()
        with self.app.app_context():
            import_rows(get_db(),[{'type':'single','stem':'后加入题目','options':['甲','乙'],'answer':'A'}])
        self.assertEqual(self.state()['total'],8)
        while True:
            state=self.submit(state)
            if state['finished']:break
            state=self.advance(state)
        self.assertEqual(self.start()['total'],9)

    def test_empty_bank_and_no_wrong_questions_have_clear_responses(self):
        response=self.client.post('/api/drill/start',json={'mode':'wrong'})
        self.assertEqual(response.status_code,400)
        self.assertIn('错题',response.json['error'])
        with self.app.app_context():get_db().execute('DELETE FROM questions');get_db().commit()
        response=self.client.post('/api/drill/start',json={'mode':'all'})
        self.assertEqual(response.status_code,400)
        self.assertIn('题库',response.json['error'])

    def test_pages_and_navigation_render_and_invalid_modes_are_rejected(self):
        for page in ('/','/drill','/wrong-book'):
            self.assertEqual(self.client.get(page).status_code,200)
        self.assertIn('全题库刷题'.encode(),self.client.get('/').data)
        self.assertEqual(self.client.post('/api/drill/start',json={'mode':'team'}).status_code,400)
        self.assertEqual(self.client.get('/api/drill/wrongs?status=invalid').status_code,400)


if __name__=='__main__':unittest.main()
