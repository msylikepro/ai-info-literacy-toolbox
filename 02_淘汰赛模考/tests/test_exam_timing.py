import json
import unittest
import test_platform as fixtures
from app import create_app,get_db,now

DEFAULT={'personal':5,'team':15,'training_personal':0,'training_team':0,'simulation':20}

class ExamTimingTest(unittest.TestCase):
    setUp=fixtures.PlatformTest.setUp
    tearDown=fixtures.PlatformTest.tearDown
    _correct=fixtures.PlatformTest._correct
    _answer_all=fixtures.PlatformTest._answer_all

    def save(self,**changes):
        timing=dict(DEFAULT,**changes)
        response=self.clients[0].post('/api/exam-timing',json=timing)
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        return timing

    def test_defaults_saved_restart_and_rule_save_independence(self):
        client=self.clients[0]
        self.assertEqual(client.get('/api/exam-timing').json,DEFAULT)
        timing=self.save(personal=2,training_team=8)
        rules=client.get('/api/exam-settings').json
        rules['personal']['single']['count']=1
        self.assertEqual(client.post('/api/exam-settings',json=rules).status_code,200)
        self.assertEqual(client.get('/api/exam-timing').json,timing)
        restarted=create_app(dict(self.app.config));other=restarted.test_client()
        other.post('/login',data={'username':'user0','password':'pass1234'})
        self.assertEqual(other.get('/api/exam-timing').json,timing)
        self.assertEqual(self.clients[1].get('/api/exam-timing').json,DEFAULT)
        self.assertEqual(other.get('/api/exam-settings').json,rules)

    def test_invalid_and_unauthorized_updates_leave_previous_values(self):
        timing=self.save(personal=2)
        for invalid in (-1,1441,1.5,True,'3',None):
            self.assertEqual(self.clients[0].post('/api/exam-timing',json=dict(timing,personal=invalid)).status_code,400)
        for invalid in ({},[],dict(timing,extra=1)):
            self.assertEqual(self.clients[0].post('/api/exam-timing',json=invalid).status_code,400)
        self.assertEqual(self.clients[0].get('/api/exam-timing').json,timing)
        self.assertEqual(self.app.test_client().post('/api/exam-timing',json=timing).status_code,401)

    def test_all_four_modes_custom_limits_and_unlimited(self):
        client=self.clients[0];client.post('/team/create',data={'name':'时间队'})
        self.save(personal=2,team=3,training_personal=4,training_team=6)
        for path,minutes in [('practice/personal',2),('practice/team',3),('training/personal',4),('training/team',6)]:
            aid=client.post('/'+path+'/start').json['attempt_id']
            paper=client.get(f'/api/attempt/{aid}').json
            self.assertEqual(paper['deadline']-paper['started_at'],minutes*60)
            self.assertEqual(paper['time_limit_minutes'],minutes)
        self.save(personal=0,team=0)
        for path in ('practice/personal','practice/team'):
            aid=client.post('/'+path+'/start').json['attempt_id']
            paper=client.get(f'/api/attempt/{aid}').json
            self.assertIsNone(paper['deadline']);self.assertIsNone(paper['remaining_seconds'])

    def test_open_paper_limit_frozen_and_custom_timeout_finalizes(self):
        client=self.clients[0];self.save(training_personal=1)
        aid=client.post('/training/personal/start').json['attempt_id']
        paper=client.get(f'/api/attempt/{aid}').json;self.save(training_personal=9)
        self.assertEqual(client.get(f'/api/attempt/{aid}').json['deadline'],paper['deadline'])
        with self.app.app_context():
            get_db().execute('UPDATE attempts SET deadline=? WHERE id=?',(now()-1,aid));get_db().commit()
        self.assertIsNotNone(client.get(f'/api/attempt/{aid}').json['submitted_at'])

    def test_simulation_frozen_stage_limits_and_total_cap(self):
        client=self.clients[0];client.post('/team/create',data={'name':'模拟时限'})
        self.save(personal=2,team=9,simulation=7)
        sid=client.post('/simulation/start').json['simulation_id']
        aid=client.get('/api/current').json['attempt']['id']
        self.assertEqual(client.get(f'/api/attempt/{aid}').json['time_limit_minutes'],2)
        self.save(personal=20,team=20,simulation=40)
        self._answer_all(client,aid)
        team=client.post(f'/simulation/{sid}/team/start').json['attempt_id']
        paper=client.get(f'/api/attempt/{team}').json
        self.assertEqual(paper['time_limit_minutes'],9)
        with self.app.app_context():deadline=get_db().execute('SELECT deadline FROM simulations WHERE id=?',(sid,)).fetchone()[0]
        self.assertEqual(paper['deadline'],deadline)
        self.assertEqual(client.get(f'/api/simulation/{sid}').json['team_limit_minutes'],9)

    def test_unlimited_simulation_and_stages_do_not_expire_or_allow_duplicate(self):
        client=self.clients[0];client.post('/team/create',data={'name':'无限模拟'})
        self.save(personal=0,team=0,simulation=0)
        sid=client.post('/simulation/start').json['simulation_id']
        self.assertIsNone(client.get(f'/api/simulation/{sid}').json['remaining_seconds'])
        self.assertEqual(client.post('/simulation/start').status_code,400)
        aid=client.get('/api/current').json['attempt']['id'];self._answer_all(client,aid)
        team=client.post(f'/simulation/{sid}/team/start').json['attempt_id']
        self.assertIsNone(client.get(f'/api/attempt/{team}').json['deadline'])
        self._answer_all(client,team)
        self.assertTrue(client.get(f'/api/simulation/{sid}').json['complete'])
