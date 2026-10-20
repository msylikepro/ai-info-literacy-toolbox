import json
from pathlib import Path
import tempfile
import unittest

from app import create_app, get_db
from importer import import_rows


class QuestionBankTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app({'TESTING':True, 'DATABASE':str(Path(self.tmp.name)/'bank.db'),
                               'SECRET_KEY':'bank-test', 'SEED':False})
        self.client = self.app.test_client()
        self.client.post('/register', data={'username':'browser', 'password':'pass1234'})
        with self.app.app_context():
            import_rows(get_db(), [
                {'type':'single','stem':'人工智能基础 GPT 特殊字符 100%_\\','options':['机器学习','自然语言处理'],'answer':'A','explanation':'单选解析'},
                {'type':'multi','stem':'人工智能应用','options':['自然语言处理','视觉识别','数据挖掘'],'answer':'AB','source':'第二题库'},
                {'type':'judge','stem':'浏览题库不影响练习','answer':'正确'}] + [
                {'type':'single','stem':f'分页题目 {i}','options':['选项甲','选项乙'],'answer':'A'} for i in range(22)])
            self.ids = [row[0] for row in get_db().execute('SELECT id FROM questions ORDER BY id')]

    def search(self, query='', page=1):
        response=self.client.get('/api/question-bank', query_string={'q':query,'page':page})
        self.assertEqual(response.status_code,200,response.data)
        return response.json

    def test_all_questions_are_paginated_once_without_answers_and_include_new_imports(self):
        first=self.search();second=self.search(page=2)
        self.assertEqual(first['total'],25)
        self.assertEqual(first['pages'],2)
        self.assertEqual(len(first['items']),20)
        self.assertEqual([r['id'] for r in first['items']+second['items']],self.ids)
        for row in first['items']+second['items']:
            self.assertIn('stem',row);self.assertIn('options',row)
            self.assertNotIn('correct',row);self.assertNotIn('answer',row);self.assertNotIn('explanation',row)
        with self.app.app_context():
            import_rows(get_db(),[{'type':'single','stem':'后续自建题库新增题','options':['甲','乙'],'answer':'B'}])
        self.assertEqual(self.search('自建题库')['total'],1)
        self.assertEqual(self.search()['total'],26)

    def test_keywords_match_stem_and_option_text_case_insensitively_and_literally(self):
        self.assertEqual(self.search('人工智能')['total'],2)
        self.assertEqual(self.search('自然语言处理')['total'],2)
        self.assertEqual(self.search('人工智能  机器学习')['total'],1)
        self.assertEqual(self.search('gPt')['total'],1)
        self.assertEqual(self.search('%_\\')['total'],1)
        self.assertEqual(self.search('不存在的词')['total'],0)
        # Option keys/JSON property names are not question content.
        self.assertEqual(self.search('"key"')['total'],0)
        self.assertEqual(self.search('   ')['total'],25)

    def test_individual_answer_requests_are_read_only_and_do_not_reveal_other_answers(self):
        state=self.client.post('/api/drill/start',json={'mode':'all'}).json['round']
        self.client.post(f"/api/favorites/{state['question']['id']}")
        def snapshot():
            with self.app.app_context():
                return {name:[tuple(row) for row in get_db().execute('SELECT * FROM '+name+' ORDER BY rowid')]
                        for name in ('questions','drill_rounds','drill_items','wrong_questions','favorite_questions','attempts','attempt_questions')}
        before=snapshot()
        for qid in self.ids[:3]:
            response=self.client.get(f'/api/question-bank/{qid}/answer')
            self.assertEqual(response.status_code,200,response.data)
            with self.app.app_context():
                expected=json.loads(get_db().execute('SELECT answer FROM questions WHERE id=?',(qid,)).fetchone()[0])
            self.assertEqual(response.json['correct'],expected)
            self.assertEqual(response.json['id'],qid)
        self.assertEqual(snapshot(),before)
        self.assertNotIn('correct',self.search()['items'][0])

    def test_requires_login_rejects_invalid_input_and_has_visible_entry(self):
        anonymous=self.app.test_client()
        self.assertEqual(anonymous.get('/api/question-bank').status_code,401)
        self.assertEqual(anonymous.get(f'/api/question-bank/{self.ids[0]}/answer').status_code,401)
        self.assertEqual(anonymous.get('/question-bank').status_code,302)
        for page in ('0','-1','abc','1.5'):
            self.assertEqual(self.client.get('/api/question-bank',query_string={'page':page}).status_code,400)
        self.assertEqual(self.client.get('/api/question-bank',query_string={'q':'字'*201}).status_code,400)
        self.assertEqual(self.client.get('/api/question-bank/999999/answer').status_code,404)
        self.assertEqual(self.search(page=999)['page'],2)
        self.assertEqual(self.client.get('/question-bank').status_code,200)
        self.assertIn('浏览题库',self.client.get('/').get_data(as_text=True))
