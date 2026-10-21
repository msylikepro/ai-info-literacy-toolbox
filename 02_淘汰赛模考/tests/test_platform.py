import io
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app import create_app


def sample(i, kind='single'):
    return {"type": kind, "stem": f"测试题 {kind} {i}", "options": ["对", "错"],
            "answer": "A", "source": "测试", "module": "测试"}


class PlatformTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATABASE": self.tmp.name + "/test.db", "SEED": False,
                               "SECRET_KEY": "test"})
        self.clients = [self.app.test_client() for _ in range(4)]
        for i, c in enumerate(self.clients):
            c.post('/register', data={"username": f"user{i}", "password": "pass1234"})
        with self.app.app_context():
            from app import get_db
            from importer import import_rows
            import_rows(get_db(), [sample(i, kind) for kind, n in [('single', 85), ('multi', 30), ('judge', 30)] for i in range(n)])

    def tearDown(self):
        self.tmp.cleanup()

    @patch('app.now', return_value=1_800_000_000)
    def test_team_simulation_and_privacy(self, _clock):
        leader, second, third, stranger = self.clients
        code = leader.post('/team/create', data={"name": "测试队"}, follow_redirects=True).json['code']
        second.post('/team/join', data={"code": code})
        third.post('/team/join', data={"code": code})
        sim = leader.post('/simulation/start').json['simulation_id']
        attempts = []
        for c in self.clients[:3]:
            a = c.get('/api/current').json['attempt']
            attempts.append(a['id'])
            self.assertEqual(a['remaining_seconds'], 300)
            self.assertEqual(a['question_count'], 10)
            self.assertEqual(len(a['questions']), 1)
            self.assertNotIn('correct', str(a['questions']))
        with self.app.app_context():
            from app import get_db
            starts = [get_db().execute('SELECT started_at,deadline FROM attempts WHERE id=?', (aid,)).fetchone() for aid in attempts]
            self.assertEqual(len({x['started_at'] for x in starts}), 1)
            self.assertTrue(all(x['deadline'] - x['started_at'] == 300 for x in starts))
        self.assertEqual(stranger.get(f'/api/attempt/{attempts[0]}').status_code, 403)
        self.assertEqual(leader.post(f'/simulation/{sim}/team/start').status_code, 400)
        for c, aid in zip(self.clients[:3], attempts):
            c.post(f'/api/attempt/{aid}/submit')
        team = leader.post(f'/simulation/{sim}/team/start').json['attempt_id']
        self.assertEqual(leader.get(f'/api/attempt/{team}').json['deadline'] - leader.get(f'/api/attempt/{team}').json['started_at'], 900)
        self.assertEqual(second.get(f'/api/attempt/{team}').status_code, 200)
        self.assertEqual(stranger.get(f'/api/attempt/{team}').status_code, 403)
        leader.post(f'/api/attempt/{team}/submit')
        result = third.get(f'/api/simulation/{sim}').json
        self.assertEqual(result['score'], 0)
        self.assertEqual(result['max_score'], 100)
        self.assertEqual(len(result['personal']), 3)
        self.assertEqual(result['duration_seconds'], sum(x['duration_seconds'] for x in result['personal']) + result['team']['duration_seconds'])
        self.assertEqual(stranger.get(f'/api/simulation/{sim}').status_code, 403)

    def test_full_score_100(self):
        leader, second, third, _ = self.clients
        code = leader.post('/team/create', data={'name': '满分队'}).json['code']
        second.post('/team/join', data={'code': code})
        third.post('/team/join', data={'code': code})
        sid = leader.post('/simulation/start').json['simulation_id']
        for client in (leader, second, third):
            aid = client.get('/api/current').json['attempt']['id']
            self._answer_all(client, aid)
            self.assertIsNotNone(client.get(f'/api/attempt/{aid}').json['submitted_at'])
        team_aid = leader.post(f'/simulation/{sid}/team/start').json['attempt_id']
        self._answer_all(leader, team_aid)
        result = second.get(f'/api/simulation/{sid}').json
        self.assertEqual(result['score'], 100)
        self.assertEqual(result['max_score'], 100)
        self.assertEqual(result['team']['score'], 40)
        self.assertEqual(result['team_max_score'], 40)
        self.assertEqual([x['score'] for x in result['personal']], [20, 20, 20])
        self.assertEqual(leader.get('/').status_code, 200)
        self.assertEqual(leader.get(f'/simulation/{sid}').status_code, 200)

    def test_one_member_can_complete_team_modes_and_simulation(self):
        leader, stranger = self.clients[:2]
        leader.post('/team/create', data={'name': '单人队'})
        home = leader.get('/').data
        for route in (b'/training/team/start', b'/practice/team/start', b'/simulation/start'):
            button = home.split(route, 1)[1].split(b'>', 1)[0]
            self.assertNotIn(b'disabled', button)

        for route in ('/training/team/start', '/practice/team/start'):
            aid = leader.post(route).json['attempt_id']
            self._answer_all(leader, aid)
            self.assertEqual(leader.get(f'/api/attempt/{aid}').json['score'], 40)
            self.assertEqual(stranger.get(f'/api/attempt/{aid}').status_code, 403)

        sid = leader.post('/simulation/start').json['simulation_id']
        personal_aid = leader.get('/api/current').json['attempt']['id']
        self.assertEqual(len(leader.get(f'/api/simulation/{sid}').json['personal']), 1)
        self._answer_all(leader, personal_aid)
        team_aid = leader.post(f'/simulation/{sid}/team/start').json['attempt_id']
        self._answer_all(leader, team_aid)
        result = leader.get(f'/api/simulation/{sid}').json
        self.assertTrue(result['complete'])
        self.assertEqual(result['score'], 60)
        self.assertEqual(result['max_score'], 60)
        self.assertEqual(result['team']['score'], 40)
        self.assertIn(b'60', leader.get('/').data)
        self.assertEqual(stranger.get(f'/api/simulation/{sid}').status_code, 403)

    def test_two_member_simulation_uses_two_personal_papers(self):
        leader, second = self.clients[:2]
        code = leader.post('/team/create', data={'name': '双人队'}).json['code']
        second.post('/team/join', data={'code': code})
        sid = leader.post('/simulation/start').json['simulation_id']
        self.assertEqual(len(leader.get(f'/api/simulation/{sid}').json['personal']), 2)
        for client in (leader, second):
            self._answer_all(client, client.get('/api/current').json['attempt']['id'])
        team_aid = second.post(f'/simulation/{sid}/team/start').json['attempt_id']
        self._answer_all(second, team_aid)
        result = leader.get(f'/api/simulation/{sid}').json
        self.assertEqual(result['score'], 80)
        self.assertEqual(result['max_score'], 80)

    def _answer_all(self, client, aid):
        with self.app.app_context():
            from app import get_db
            rows = get_db().execute('''SELECT q.answer FROM questions q JOIN attempt_questions aq ON q.id=aq.question_id
                  WHERE aq.attempt_id=? ORDER BY aq.position''', (aid,)).fetchall()
        for i, row in enumerate(rows):
            self.assertEqual(client.post(f'/api/attempt/{aid}/answer', json={'index': i, 'answer': json.loads(row['answer'])}).status_code, 200)
            self.assertEqual(client.post(f'/api/attempt/{aid}/advance', json={'index': i, 'skip': False}).status_code, 200)

    def test_fixed_mix_and_forward_only_skip(self):
        client = self.clients[0]
        aid = client.post('/practice/personal/start').json['attempt_id']
        with self.app.app_context():
            from app import get_db
            rows = get_db().execute('''SELECT q.type FROM questions q JOIN attempt_questions aq ON aq.question_id=q.id
              WHERE aq.attempt_id=? ORDER BY aq.position''', (aid,)).fetchall()
        self.assertEqual({k: sum(x['type'] == k for x in rows) for k in ('single', 'multi', 'judge')},
                         {'single': 6, 'multi': 2, 'judge': 2})
        self.assertEqual([x['type'] for x in rows], ['single']*6 + ['multi']*2 + ['judge']*2)
        first = client.get(f'/api/attempt/{aid}').json
        self.assertEqual(first['current_position'], 0)
        self.assertEqual(len(first['questions']), 1)
        self.assertIn('跳过后无法返回'.encode(), client.get(f'/exam/{aid}').data)
        self.assertEqual(client.post(f'/api/attempt/{aid}/advance', json={'index': 0, 'skip': False}).status_code, 400)
        correct = self._correct(aid, 0)
        self.assertEqual(client.post(f'/api/attempt/{aid}/answer', json={'index': 0, 'answer': correct}).status_code, 200)
        self.assertEqual(client.post(f'/api/attempt/{aid}/advance', json={'index': 0, 'skip': True}).status_code, 200)
        second = client.get(f'/api/attempt/{aid}').json
        self.assertEqual(second['current_position'], 1)
        self.assertEqual(len(second['questions']), 1)
        self.assertNotEqual(first['questions'][0]['stem'], second['questions'][0]['stem'])
        self.assertNotIn(first['questions'][0]['stem'], json.dumps(second, ensure_ascii=False))
        self.assertEqual(client.post(f'/api/attempt/{aid}/answer', json={'index': 0, 'answer': correct}).status_code, 409)
        client.post(f'/api/attempt/{aid}/submit')
        result = client.get(f'/api/attempt/{aid}').json
        self.assertEqual(result['questions'][0]['answer'], [])
        self.assertEqual(result['questions'][0]['points'], 0)
        self.assertEqual(result['max_score'], 20)

    def test_untimed_personal_training_tracks_each_question(self):
        client = self.clients[0]
        response = client.post('/training/personal/start')
        self.assertEqual(response.status_code, 200)
        aid = response.json['attempt_id']
        active = client.get(f'/api/attempt/{aid}').json
        self.assertEqual(active['kind'], 'training_personal')
        self.assertIsNone(active['deadline'])
        self.assertIsNone(active['remaining_seconds'])
        self.assertIn('个人练习 · 10题 / 不限时'.encode(), client.get('/').data)
        self.assertIn('每题用时'.encode(), client.get(f'/exam/{aid}').data)
        with self.app.app_context():
            from app import get_db, now
            db = get_db()
            db.execute('UPDATE attempts SET question_started_at=? WHERE id=?', (now()-7, aid))
            db.commit()
        client.post(f'/api/attempt/{aid}/answer', json={'index': 0, 'answer': self._correct(aid, 0)})
        client.post(f'/api/attempt/{aid}/advance', json={'index': 0, 'skip': False})
        with self.app.app_context():
            from app import get_db, now
            db = get_db()
            db.execute('UPDATE attempts SET question_started_at=? WHERE id=?', (now()-4, aid))
            db.commit()
        result = client.post(f'/api/attempt/{aid}/submit').json['attempt']
        self.assertEqual(result['score'], 2)
        self.assertEqual(result['max_score'], 20)
        self.assertGreaterEqual(result['questions'][0]['duration_seconds'], 7)
        self.assertGreaterEqual(result['questions'][1]['duration_seconds'], 4)
        self.assertIsNone(result['questions'][2]['duration_seconds'])

    def test_untimed_team_training_is_shared(self):
        leader, second, third, stranger = self.clients
        code = leader.post('/team/create', data={'name': '训练队'}).json['code']
        second.post('/team/join', data={'code': code})
        third.post('/team/join', data={'code': code})
        response = leader.post('/training/team/start')
        self.assertEqual(response.status_code, 200)
        aid = response.json['attempt_id']
        self.assertIsNone(second.get(f'/api/attempt/{aid}').json['deadline'])
        self.assertEqual(stranger.get(f'/api/attempt/{aid}').status_code, 403)
        second.post(f'/api/attempt/{aid}/answer', json={'index': 0, 'answer': self._correct(aid, 0)})
        third.post(f'/api/attempt/{aid}/submit')
        result = leader.get(f'/api/attempt/{aid}').json
        self.assertEqual(result['score'], 4)
        self.assertEqual(result['max_score'], 40)
        self.assertIsNotNone(result['questions'][0]['duration_seconds'])

    def test_timed_attempt_tracks_question_time_on_advance_and_timeout(self):
        client = self.clients[0]
        aid = client.post('/practice/personal/start').json['attempt_id']
        with self.app.app_context():
            from app import get_db, now
            db = get_db()
            db.execute('UPDATE attempts SET question_started_at=? WHERE id=?', (now()-9, aid))
            db.commit()
        client.post(f'/api/attempt/{aid}/advance', json={'index': 0, 'skip': True})
        with self.app.app_context():
            from app import get_db, now
            db = get_db()
            db.execute('UPDATE attempts SET deadline=?,question_started_at=? WHERE id=?', (now()-1, now()-5, aid))
            db.commit()
        result = client.get(f'/api/attempt/{aid}').json
        self.assertIsNotNone(result['submitted_at'])
        self.assertGreaterEqual(result['questions'][0]['duration_seconds'], 9)
        self.assertEqual(result['questions'][1]['duration_seconds'], 4)
        self.assertIsNone(result['questions'][2]['duration_seconds'])

    def test_team_practice_has_same_mix_and_scoring(self):
        leader, second, third, _ = self.clients
        code = leader.post('/team/create', data={'name': '计分队'}).json['code']
        second.post('/team/join', data={'code': code})
        third.post('/team/join', data={'code': code})
        aid = leader.post('/practice/team/start').json['attempt_id']
        first = leader.get(f'/api/attempt/{aid}').json
        self.assertEqual(first['deadline'] - first['started_at'], 900)
        with self.app.app_context():
            from app import get_db
            types = [r[0] for r in get_db().execute('''SELECT q.type FROM questions q JOIN attempt_questions aq
                ON q.id=aq.question_id WHERE aq.attempt_id=?''', (aid,))]
        self.assertEqual([types.count(k) for k in ('single', 'multi', 'judge')], [6, 2, 2])
        correct = self._correct(aid, 0)
        leader.post(f'/api/attempt/{aid}/answer', json={'index': 0, 'answer': correct})
        leader.post(f'/api/attempt/{aid}/advance', json={'index': 0, 'skip': False})
        options = [x['key'] for x in second.get(f'/api/attempt/{aid}').json['questions'][0]['options']]
        wrong = next(x for x in options if x not in self._correct(aid, 1))
        second.post(f'/api/attempt/{aid}/answer', json={'index': 1, 'answer': [wrong]})
        third.post(f'/api/attempt/{aid}/submit')
        result = leader.get(f'/api/attempt/{aid}').json
        self.assertEqual(result['score'], 3)
        self.assertEqual(result['max_score'], 40)
        self.assertEqual(result['questions'][0]['points'], 4)
        self.assertEqual(result['questions'][1]['points'], -1)

    def test_existing_database_adds_cursor_column(self):
        path = self.tmp.name + '/old.db'
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE attempts(id INTEGER PRIMARY KEY,kind TEXT,user_id INTEGER,team_id INTEGER,simulation_id INTEGER,started_at INTEGER,deadline INTEGER,submitted_at INTEGER,score REAL,answers TEXT NOT NULL DEFAULT '{}')")
        db.execute('CREATE TABLE attempt_questions(attempt_id INTEGER,position INTEGER,question_id INTEGER,PRIMARY KEY(attempt_id,position))')
        db.commit()
        db.close()
        old_app = create_app({'TESTING': True, 'DATABASE': path, 'SEED': False, 'SECRET_KEY': 'test'})
        with old_app.app_context():
            from app import get_db
            columns = [r['name'] for r in get_db().execute('PRAGMA table_info(attempts)')]
            self.assertIn('current_position', columns)
            self.assertIn('question_started_at', columns)
            self.assertIn('correct_points', columns)
            question_columns = [r['name'] for r in get_db().execute('PRAGMA table_info(attempt_questions)')]
            self.assertIn('duration_seconds', question_columns)

    def test_insufficient_question_type_is_explicit(self):
        with self.app.app_context():
            from app import get_db
            db = get_db()
            db.execute("DELETE FROM questions WHERE type='judge'")
            db.commit()
        result = self.clients[0].post('/practice/personal/start')
        self.assertEqual(result.status_code, 400)
        self.assertIn('判断', result.json['error'])

    def test_legacy_20_question_record_keeps_old_scoring(self):
        client = self.clients[0]
        aid = client.post('/practice/personal/start').json['attempt_id']
        with self.app.app_context():
            from app import get_db
            db = get_db()
            ids = [x[0] for x in db.execute("SELECT id FROM questions WHERE type='single' LIMIT 20")]
            db.execute('DELETE FROM attempt_questions WHERE attempt_id=?', (aid,))
            db.executemany('INSERT INTO attempt_questions(attempt_id,position,question_id) VALUES(?,?,?)',
                           [(aid, i, qid) for i, qid in enumerate(ids)])
            # Imported history predates rule snapshots; a new paper's snapshot
            # must not be used to stand in for a legacy record.
            db.execute('UPDATE attempts SET answers=?,rules_json=NULL WHERE id=?', (json.dumps({'0': ['A']}), aid))
            db.commit()
        result = client.post(f'/api/attempt/{aid}/submit').json['attempt']
        self.assertEqual(result['score'], 1)
        self.assertEqual(result['max_score'], 20)
        self.assertEqual(result['questions'][0]['points'], 1)

    def test_existing_10_question_team_paper_keeps_two_point_rule(self):
        leader, second, third, _ = self.clients
        code = leader.post('/team/create', data={'name': '旧团队卷'}).json['code']
        second.post('/team/join', data={'code': code})
        third.post('/team/join', data={'code': code})
        aid = leader.post('/practice/team/start').json['attempt_id']
        with self.app.app_context():
            from app import get_db
            db = get_db()
            db.execute('UPDATE attempts SET correct_points=2,rules_json=NULL WHERE id=?', (aid,))
            db.commit()
        leader.post(f'/api/attempt/{aid}/answer', json={'index': 0, 'answer': self._correct(aid, 0)})
        result = second.post(f'/api/attempt/{aid}/submit').json['attempt']
        self.assertEqual(result['score'], 2)
        self.assertEqual(result['max_score'], 20)
        self.assertEqual(result['questions'][0]['points'], 2)

    def _correct(self, aid, index):
        with self.app.app_context():
            from app import get_db
            row = get_db().execute('''SELECT q.answer FROM questions q JOIN attempt_questions aq ON aq.question_id=q.id
               WHERE aq.attempt_id=? AND aq.position=?''', (aid, index)).fetchone()
            return json.loads(row['answer'])

    def test_admin_upload_preview_and_access(self):
        client, other = self.clients[:2]
        self.assertEqual(other.get('/admin/import').status_code, 403)
        with self.app.app_context():
            from app import get_db
            get_db().execute('UPDATE users SET is_admin=1 WHERE username=?', ('user0',))
            get_db().commit()
        row = sample(999)
        response = client.post('/admin/import', data={'file': (io.BytesIO(json.dumps([row, row]).encode()), 'new.json'), 'source': '测试来源'}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200)
        self.assertIn('预计新增 1'.encode(), response.data)
        self.assertIn('重复 1'.encode(), response.data)
        with client.session_transaction() as state:
            token = state['import_token']
        commit = client.post('/admin/import/commit', data={'token': token})
        self.assertEqual(commit.status_code, 200)
        self.assertIn('新增 1'.encode(), commit.data)

    def test_server_deadline_submits_and_rejects_changes(self):
        client = self.clients[0]
        aid = client.post('/practice/personal/start').json['attempt_id']
        with self.app.app_context():
            from app import get_db, now
            db = get_db()
            db.execute('UPDATE attempts SET started_at=?,deadline=? WHERE id=?', (now()-300, now()-1, aid))
            db.commit()
        result = client.get(f'/api/attempt/{aid}').json
        self.assertIsNotNone(result['submitted_at'])
        self.assertEqual(result['duration_seconds'], 299)
        self.assertEqual(client.post(f'/api/attempt/{aid}/answer', json={'index': 0, 'answer': ['A']}).status_code, 409)

    def test_simulation_20_minute_cutoff_without_team_start(self):
        leader, second, third, _ = self.clients
        code = leader.post('/team/create', data={'name': '超时队'}).json['code']
        second.post('/team/join', data={'code': code})
        third.post('/team/join', data={'code': code})
        sid = leader.post('/simulation/start').json['simulation_id']
        with self.app.app_context():
            from app import get_db, now
            db = get_db()
            db.execute('UPDATE simulations SET started_at=?,deadline=? WHERE id=?', (now()-1200, now()-1, sid))
            db.execute('UPDATE attempts SET started_at=?,deadline=? WHERE simulation_id=? AND kind="sim_personal"',
                       (now()-1200, now()-900, sid))
            db.commit()
        result = leader.get(f'/api/simulation/{sid}').json
        self.assertTrue(result['complete'])
        self.assertEqual(result['team']['score'], 0)
        self.assertEqual(result['team']['duration_seconds'], 0)

    def test_source_variants_and_implicit_judge(self):
        from pathlib import Path
        from importer import parse_file, normalize_row, fingerprint
        rows = parse_file('source_bank.json', (Path(__file__).parents[1] / 'data/source_bank.json').read_bytes())
        variants = [x for x in rows if x.get('original_id', '').startswith('M01-')]
        self.assertEqual(len(variants), 2)
        self.assertNotEqual(fingerprint(normalize_row(variants[0])), fingerprint(normalize_row(variants[1])))
        implicit = next(x for x in rows if x.get('id') == 'O09')
        self.assertEqual(len(normalize_row(implicit)['options']), 2)

    def test_csv_and_xlsx_import_formats(self):
        from importer import parse_file, normalize_row
        csv_data = 'type,stem,A,B,answer,source\nsingle,CSV题,甲,乙,A,自编\n'.encode('utf-8')
        self.assertEqual(normalize_row(parse_file('bank.csv', csv_data)[0])['stem'], 'CSV题')
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(['题型', '题干', 'A', 'B', '答案', '解析'])
        book.active.append(['判断', 'XLSX题', '正确', '错误', 'A', '说明'])
        stream = io.BytesIO()
        book.save(stream)
        row = normalize_row(parse_file('bank.xlsx', stream.getvalue())[0])
        self.assertEqual(row['answer'], ['A'])
        self.assertEqual(row['explanation'], '说明')

    def test_import_dedup_and_preview(self):
        from importer import normalize_row, fingerprint, import_rows
        a = sample(100)
        b = dict(a, options=["错", "对"], answer="B")
        c = dict(a, options=["其他", "对"])
        self.assertEqual(fingerprint(normalize_row(a)), fingerprint(normalize_row(b)))
        self.assertNotEqual(fingerprint(normalize_row(a)), fingerprint(normalize_row(c)))
        with self.app.app_context():
            from app import get_db
            stats = import_rows(get_db(), [a, b, c, {"stem": "bad"}])
            self.assertEqual(stats, {"added": 2, "duplicate": 1, "invalid": 1})

    def test_score_and_tie_order(self):
        from app import score_answer, ranking_key
        self.assertEqual(score_answer('personal', ['A'], ['A']), 2)
        self.assertEqual(score_answer('personal', ['B'], ['A']), -1)
        self.assertEqual(score_answer('personal', [], ['A']), 0)
        self.assertEqual(score_answer('team', ['A', 'B'], ['A', 'B']), 2)
        self.assertEqual(score_answer('team', ['A'], ['A', 'B']), -1)
        self.assertLess(ranking_key({"score": 50, "duration_seconds": 99}), ranking_key({"score": 50, "duration_seconds": 100}))


if __name__ == '__main__':
    unittest.main()
