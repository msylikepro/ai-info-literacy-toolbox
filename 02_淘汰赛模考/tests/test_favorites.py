import json
from pathlib import Path
import tempfile
import unittest

from app import create_app, get_db
from importer import import_rows


class FavoritesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {'TESTING': True, 'DATABASE': str(Path(self.tmp.name)/'test.db'),
                       'SECRET_KEY': 'favorite-test', 'SEED': False}
        self.app = create_app(self.config)
        self.client, self.other = self.app.test_client(), self.app.test_client()
        self.client.post('/register', data={'username': 'collector', 'password': 'pass1234'})
        self.other.post('/register', data={'username': 'other', 'password': 'pass1234'})
        with self.app.app_context():
            import_rows(get_db(), [
                {'type': 'single', 'stem': '收藏单选', 'options': ['甲', '乙'], 'answer': 'A', 'explanation': '单选解析'},
                {'type': 'multi', 'stem': '收藏多选', 'options': ['甲', '乙', '丙'], 'answer': 'AB'},
                {'type': 'judge', 'stem': '收藏判断', 'answer': '正确'}])
            self.ids = {r['type']: r['id'] for r in get_db().execute('SELECT id,type FROM questions')}

    def add(self, qid):
        result = self.client.post(f'/api/favorites/{qid}')
        self.assertEqual(result.status_code, 200, result.data)
        return result.json

    def test_bookmark_is_idempotent_persistent_per_account_and_removal_keeps_question(self):
        qid = self.ids['single']
        self.assertEqual(self.add(qid)['total'], 1)
        self.assertEqual(self.add(qid)['total'], 1)
        self.assertEqual(self.other.get('/api/favorites').json['total'], 0)
        self.assertEqual(self.other.get(f'/api/favorites/{qid}').status_code, 404)
        restarted = create_app(self.config).test_client()
        restarted.post('/login', data={'username': 'collector', 'password': 'pass1234'})
        listing = restarted.get('/api/favorites').json
        self.assertEqual(listing['total'], 1)
        self.assertEqual(listing['items'][0]['id'], qid)
        for _ in range(2):
            self.assertEqual(self.client.delete(f'/api/favorites/{qid}').json['total'], 0)
        self.assertEqual(self.client.get(f'/api/favorites/{qid}').status_code, 404)
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM questions').fetchone()[0], 3)

    def test_answers_hidden_until_explicit_reveal_or_valid_submission(self):
        for kind, qid in self.ids.items():
            self.add(qid)
            question = self.client.get(f'/api/favorites/{qid}').json
            self.assertNotIn('correct', question)
            self.assertNotIn('explanation', question)
            with self.app.app_context():
                answer = json.loads(get_db().execute('SELECT answer FROM questions WHERE id=?', (qid,)).fetchone()[0])
            revealed = self.client.post(f'/api/favorites/{qid}/reveal').json
            self.assertEqual(revealed['correct'], answer)
            self.assertNotIn('is_correct', revealed)
            checked = self.client.post(f'/api/favorites/{qid}/answer', json={'answer': answer})
            self.assertEqual(checked.status_code, 200, checked.data)
            self.assertTrue(checked.json['is_correct'])
            self.assertEqual(checked.json['correct'], answer)
            for invalid in ([], ['Z'], ['A', 'A'], 'A', None, [True]):
                self.assertEqual(self.client.post(f'/api/favorites/{qid}/answer', json={'answer': invalid}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/favorites/{self.ids['single']}/answer", json={'answer': ['A','B']}).status_code, 400)

    def test_drill_flag_updates_without_changing_round_or_any_practice_records(self):
        state = self.client.post('/api/drill/start', json={'mode': 'all'}).json['round']
        qid = state['question']['id']
        self.assertFalse(state['question']['favorited'])
        def snapshot():
            with self.app.app_context():
                return {table: [tuple(r) for r in get_db().execute('SELECT * FROM '+table+' ORDER BY rowid')]
                        for table in ('drill_rounds', 'drill_items', 'wrong_questions', 'attempts', 'attempt_questions')}
        original = snapshot()
        self.add(self.ids['single'])
        for answer in (['B'], ['A']):
            self.assertEqual(self.client.post(f"/api/favorites/{self.ids['single']}/answer", json={'answer': answer}).status_code, 200)
        self.assertEqual(snapshot(), original)
        self.add(qid)
        current = self.client.get('/api/drill/current').json['round']
        self.assertTrue(current['question']['favorited'])
        self.assertEqual(current['id'], state['id'])
        for answer in ([o['key'] for o in current['question']['options']][:1],):
            for _ in range(2):
                self.assertEqual(self.client.post(f'/api/favorites/{qid}/answer', json={'answer': answer}).status_code, 200)
        self.client.post(f'/api/favorites/{qid}/reveal')
        self.client.delete(f'/api/favorites/{qid}')
        self.assertFalse(self.client.get('/api/drill/current').json['round']['question']['favorited'])
        self.assertEqual(snapshot(), original)

    def test_authentication_access_checks_missing_questions_and_page_entry(self):
        qid = self.ids['single']
        anon = self.app.test_client()
        for method, route in [('get', '/api/favorites'), ('post', f'/api/favorites/{qid}'),
                              ('delete', f'/api/favorites/{qid}'), ('post', f'/api/favorites/{qid}/reveal')]:
            self.assertEqual(getattr(anon, method)(route).status_code, 401)
        self.assertEqual(self.client.post('/api/favorites/999999').status_code, 404)
        self.add(qid)
        for suffix in ('answer', 'reveal'):
            self.assertEqual(self.other.post(f'/api/favorites/{qid}/{suffix}', json={'answer': ['A']}).status_code, 404)
        self.assertEqual(self.other.delete(f'/api/favorites/{qid}').status_code, 200)
        self.assertEqual(self.client.get('/api/favorites').json['total'], 1)
        self.assertEqual(self.client.get('/favorites').status_code, 200)
        self.assertIn('我的收藏集', self.client.get('/').get_data(as_text=True))
        self.assertIn('drill-favorite', self.client.get('/drill').get_data(as_text=True))
