import copy
import json
import unittest
from app import create_app, get_db, now
import test_platform as fixtures


def rules(counts=(2,1,1), correct=3, wrong=-0.5, unanswered=-0.25):
    return {kind:dict(count=count,correct=correct,wrong=wrong,unanswered=unanswered)
            for kind,count in zip(('single','multi','judge'),counts)}


class ExamRulesTest(unittest.TestCase):
    setUp=fixtures.PlatformTest.setUp
    tearDown=fixtures.PlatformTest.tearDown
    _correct=fixtures.PlatformTest._correct
    _answer_all=fixtures.PlatformTest._answer_all

    def save(self, personal=None, team=None):
        data={'personal':personal or rules(),'team':team or rules((1,2,0),5,-2,-1)}
        response=self.clients[0].post('/api/exam-settings',json=data)
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        return data

    def test_profile_defaults_persistence_and_account_isolation(self):
        client=self.clients[0]
        default=client.get('/api/exam-settings')
        self.assertEqual(default.status_code,200)
        self.assertEqual(default.json['personal']['single'],dict(count=6,correct=2,wrong=-1,unanswered=0))
        data=self.save()
        restarted=create_app(dict(self.app.config))
        c=restarted.test_client();c.post('/login',data={'username':'user0','password':'pass1234'})
        self.assertEqual(c.get('/api/exam-settings').json,data)
        self.assertEqual(self.clients[1].get('/api/exam-settings').json,default.json)
        self.assertEqual(self.app.test_client().post('/api/exam-settings',json=data).status_code,401)
        self.assertEqual(client.post('/api/exam-settings',json=data,headers={'Origin':'https://foreign.invalid'}).status_code,403)

    def test_invalid_settings_reject_without_partial_save(self):
        saved=self.save()
        invalid=[]
        for field,value in [('count',True),('count',1.5),('count',-1),('count',501),('correct',float('nan')),
                            ('correct',float('inf')),('correct',-1),('wrong',1001),('wrong',4),
                            ('unanswered',-0.001),('correct','3')]:
            data=copy.deepcopy(saved);data['personal']['single'][field]=value;invalid.append(data)
        data=copy.deepcopy(saved);data['personal']=rules((0,0,0));invalid.append(data)
        data=copy.deepcopy(saved);data['team']=rules((200,200,101));invalid.append(data)
        data=copy.deepcopy(saved);del data['team']['multi'];invalid.append(data)
        invalid += [[], {'personal':saved['personal']},dict(saved,extra=True)]
        for data in invalid:
            with self.subTest(data=data):
                self.assertEqual(self.clients[0].post('/api/exam-settings',json=data).status_code,400)
                self.assertEqual(self.clients[0].get('/api/exam-settings').json,saved)

    def test_personal_custom_scoring_is_locked_and_review_has_true_outcomes(self):
        client=self.clients[0];data=self.save()
        aid=client.post('/training/personal/start').json['attempt_id']
        active=client.get(f'/api/attempt/{aid}').json
        self.assertEqual(active['question_count'],4);self.assertEqual(active['max_score'],12)
        self.assertEqual(active['scoring_rules'],data['personal'])
        self.assertNotIn('correct',active['questions'][0])
        self.save(personal=rules((1,0,0),100,0,0))
        client.post(f'/api/attempt/{aid}/answer',json={'index':0,'answer':self._correct(aid,0)})
        client.post(f'/api/attempt/{aid}/advance',json={'index':0,'skip':False})
        client.post(f'/api/attempt/{aid}/answer',json={'index':1,'answer':['B']})
        client.post(f'/api/attempt/{aid}/advance',json={'index':1,'skip':False})
        result=client.post(f'/api/attempt/{aid}/submit').json['attempt']
        self.assertEqual(result['score'],2)
        self.assertEqual([q['points'] for q in result['questions']],[3,-0.5,-0.25,-0.25])
        self.assertEqual([q['outcome'] for q in result['questions']],['correct','wrong','unanswered','unanswered'])
        self.assertEqual(result['max_score'],12)
        self.assertIn('2.0 / 12'.encode(),client.get('/').data)

    def test_team_config_and_twenty_question_custom_paper_are_not_legacy(self):
        client=self.clients[0];client.post('/team/create',data={'name':'自定义队'})
        self.save(team=rules((12,4,4),3.25,0,-1))
        for route in ('/practice/team/start','/training/team/start'):
            aid=client.post(route).json['attempt_id'];active=client.get(f'/api/attempt/{aid}').json
            self.assertEqual(active['question_count'],20);self.assertEqual(active['max_score'],65)
            self._answer_all(client,aid)
            result=client.get(f'/api/attempt/{aid}').json
            self.assertEqual(result['score'],65);self.assertEqual(result['questions'][0]['points'],3.25)

    def test_custom_simulation_uses_both_profiles_disjoint_and_correct_totals(self):
        leader,second=self.clients[:2]
        code=leader.post('/team/create',data={'name':'双人自定义'}).json['code'];second.post('/team/join',data={'code':code})
        self.save(personal=rules((1,1,0),2.5,-1,-0.5),team=rules((0,1,2),4,-2,-1))
        sid=leader.post('/simulation/start').json['simulation_id']
        with self.app.app_context():
            ids=[r[0] for r in get_db().execute('SELECT question_id FROM attempt_questions aq JOIN attempts a ON a.id=aq.attempt_id WHERE a.simulation_id=?',(sid,))]
            self.assertEqual(len(ids),7);self.assertEqual(len(set(ids)),7)
        for client in (leader,second):self._answer_all(client,client.get('/api/current').json['attempt']['id'])
        # Changing settings between phases must not change the waiting team paper.
        self.save(team=rules((1,0,0),100,0,0))
        team=second.post(f'/simulation/{sid}/team/start').json['attempt_id'];self._answer_all(second,team)
        result=leader.get(f'/api/simulation/{sid}').json
        self.assertEqual(result['score'],22);self.assertEqual(result['max_score'],22)
        self.assertEqual([p['max_score'] for p in result['personal']],[5,5])
        self.assertEqual(result['team_max_score'],12)
        self.assertIn(b'22',leader.get('/').data)

    def test_insufficient_stock_uses_combined_profiles_and_creates_no_attempts(self):
        leader,second=self.clients[:2]
        code=leader.post('/team/create',data={'name':'不足队'}).json['code'];second.post('/team/join',data={'code':code})
        self.save(personal=rules((40,0,0)),team=rules((6,0,0)))
        with self.app.app_context():before=get_db().execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
        response=leader.post('/simulation/start')
        self.assertEqual(response.status_code,400);self.assertIn('86',response.json['error'])
        with self.app.app_context():self.assertEqual(get_db().execute('SELECT COUNT(*) FROM attempts').fetchone()[0],before)

    def test_deadline_not_started_team_uses_unanswered_points(self):
        client=self.clients[0];client.post('/team/create',data={'name':'超时队'})
        self.save(personal=rules((1,0,0)),team=rules((1,1,0),4,-2,-0.75))
        sid=client.post('/simulation/start').json['simulation_id']
        with self.app.app_context():
            db=get_db();db.execute('UPDATE simulations SET deadline=? WHERE id=?',(now()-1,sid))
            db.execute('UPDATE attempts SET deadline=? WHERE simulation_id=? AND kind="sim_personal"',(now()-1,sid));db.commit()
        result=client.get(f'/api/simulation/{sid}').json
        self.assertTrue(result['complete']);self.assertEqual(result['team']['score'],-1.5)
        self.assertEqual(result['score'],-1.75)

    def test_decimal_totals_and_zero_correct_score_do_not_confuse_outcomes(self):
        client=self.clients[0];self.save(personal=rules((3,0,0),0.1,0,-0.1))
        aid=client.post('/practice/personal/start').json['attempt_id'];self._answer_all(client,aid)
        result=client.get(f'/api/attempt/{aid}').json
        self.assertEqual(result['score'],0.3);self.assertEqual(result['max_score'],0.3)
        self.save(personal=rules((1,0,0),0,0,0))
        aid=client.post('/training/personal/start').json['attempt_id'];self._answer_all(client,aid)
        self.assertEqual(client.get(f'/api/attempt/{aid}').json['questions'][0]['outcome'],'correct')

    def test_each_type_uses_its_own_correct_wrong_and_unanswered_values(self):
        profile=rules((1,1,1))
        for kind,correct,wrong,unanswered in [('single',1.25,0,-0.1),('multi',2.5,-0.5,0.2),('judge',5,-2,-0.3)]:
            profile[kind].update(correct=correct,wrong=wrong,unanswered=unanswered)
        self.save(personal=profile)
        client=self.clients[0]
        aid=client.post('/training/personal/start').json['attempt_id'];self._answer_all(client,aid)
        self.assertEqual(client.get(f'/api/attempt/{aid}').json['score'],8.75)
        aid=client.post('/training/personal/start').json['attempt_id']
        result=client.post(f'/api/attempt/{aid}/submit').json['attempt']
        self.assertEqual(result['score'],-0.2)
        self.assertEqual([q['points'] for q in result['questions']],[-0.1,0.2,-0.3])
        aid=client.post('/training/personal/start').json['attempt_id']
        for i in range(3):
            client.post(f'/api/attempt/{aid}/answer',json={'index':i,'answer':['B']})
            client.post(f'/api/attempt/{aid}/advance',json={'index':i,'skip':False})
        result=client.get(f'/api/attempt/{aid}').json
        self.assertEqual(result['score'],-2.5)
        self.assertEqual([q['outcome'] for q in result['questions']],['wrong']*3)
