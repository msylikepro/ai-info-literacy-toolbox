import json
from pathlib import Path
import tempfile
import unittest
import sqlite3
import threading
from unittest.mock import patch

from app import create_app, get_db, question_count
from importer import normalize_row, fingerprint, parse_file, import_rows, inspect_rows


ROOT = Path(__file__).resolve().parents[1]


def reviewed_fixture(min_members=2, exclude=()):
    manifest=json.loads((ROOT/'data/reviewed_duplicate_groups.json').read_text(encoding='utf-8'))
    bank={}
    for name in ('source_questions.json','source_bank.json'):
        for raw in parse_file(name,(ROOT/'data'/name).read_bytes()):
            bank.setdefault(fingerprint(normalize_row(raw)),normalize_row(raw))
    for group in manifest['groups']:
        marks=[member['fingerprint'] for member in group['members']]
        if len(marks)>=min_members and not set(marks)&set(exclude):
            return [bank[mark] for mark in marks]
    raise AssertionError('Missing reviewed fixture')


def reordered_reviewed_pair():
    first,second=reviewed_fixture()[:2]
    # Keep the audited option texts/fingerprint, but change which letter means what.
    swap={'A':'B','B':'A'}
    second['options']=[dict(option,key=swap.get(option['key'],option['key'])) for option in second['options']]
    second['answer']=[swap.get(key,key) for key in second['answer']]
    return [first,second]


def insert_legacy(db, raw):
    row = normalize_row(raw)
    return db.execute('''INSERT INTO questions(fingerprint,type,stem,options,answer,source,module,original_id,explanation)
      VALUES(?,?,?,?,?,?,?,?,?)''', (fingerprint(row), row['type'], row['stem'], json.dumps(row['options']),
      json.dumps(row['answer']), row['source'], row['module'], row['original_id'], row['explanation'])).lastrowid


def item(stem, answer='A', options=None):
    return {'type':'single', 'stem':stem, 'options':options or ['甲','乙'], 'answer':answer}


class DistillationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {'TESTING':True, 'DATABASE':str(Path(self.tmp.name)/'test.db'),
                       'SECRET_KEY':'dedup-test', 'SEED':False}
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.client.post('/register', data={'username':'dedup-user','password':'pass1234'})

    def test_seed_and_legacy_migration_have_229_effective_questions_without_changing_rows(self):
        with self.app.app_context():
            db=get_db(); seen=set()
            for name in ('source_questions.json','source_bank.json'):
                for raw in parse_file(name,(ROOT/'data'/name).read_bytes()):
                    mark=fingerprint(normalize_row(raw))
                    if mark not in seen:
                        insert_legacy(db,raw);seen.add(mark)
            db.commit()
            before=[tuple(r) for r in db.execute('SELECT * FROM questions ORDER BY id')]
            self.assertEqual(len(before),373)
        migrated=create_app(self.config)
        with migrated.app_context():
            self.assertEqual(question_count(),229)
            self.assertEqual([tuple(r) for r in get_db().execute('SELECT * FROM questions ORDER BY id')],before)
        fresh=create_app(dict(self.config,DATABASE=str(Path(self.tmp.name)/'fresh.db'),SEED=True))
        with fresh.app_context():
            self.assertEqual(question_count(),229)
        client=fresh.test_client()
        client.post('/register',data={'username':'seed-test','password':'pass1234'})
        state=client.post('/api/drill/start',json={'mode':'all'}).json
        self.assertEqual(state['round']['total'],229)
        self.assertEqual(state['bank_count'],229)
        self.assertEqual(client.get('/api/question-bank').json['total'],229)
        exam=client.post('/practice/personal/start')
        self.assertEqual(exam.status_code,200,exam.data)
        with fresh.app_context():
            self.assertEqual(get_db().execute('''SELECT COUNT(*) FROM attempt_questions aq
              JOIN question_duplicates d ON d.alias_id=aq.question_id WHERE aq.attempt_id=?''',
              (exam.json['attempt_id'],)).fetchone()[0],0)
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM questions').fetchone()[0],373)
            for name in ('source_questions.json','source_bank.json'):
                counts=import_rows(get_db(),parse_file(name,(ROOT/'data'/name).read_bytes()))
                self.assertEqual(counts['added'],0)
            self.assertEqual(question_count(),229)

    def test_future_format_import_is_idempotent_and_maps_reordered_answer_content(self):
        rows=[item('中文 AI 问题（ ）',options=['甲','乙']),
              item('\n中文  AI 问题( )\n',answer='B',options=['乙','甲'])]
        with self.app.app_context():
            counts,preview=inspect_rows(get_db(),rows)
            self.assertEqual(counts,{'added':1,'duplicate':1,'invalid':0})
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM questions').fetchone()[0],0)
            self.assertEqual(import_rows(get_db(),rows),counts)
            self.assertEqual(question_count(),1)
            self.assertEqual(import_rows(get_db(),rows)['added'],0)
            self.assertEqual(question_count(),1)

    def test_conflicting_answers_are_saved_for_review_and_not_silently_deduplicated(self):
        with self.app.app_context():
            import_rows(get_db(),[item('相同题干')])
            counts,preview=inspect_rows(get_db(),[item('相同题干',answer='B')])
            self.assertEqual(counts['invalid'],1)
            self.assertEqual(counts['conflict'],1)
            self.assertIn('答案',preview[0]['stem'])
            import_rows(get_db(),[item('相同题干',answer='B')])
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM question_import_conflicts').fetchone()[0],1)
            self.assertEqual(question_count(),1)

    def test_admin_can_see_retained_conflicting_import_content(self):
        with self.app.app_context():
            db=get_db()
            import_rows(db,[item('需要人工检查的题')])
            import_rows(db,[item('需要人工检查的题',answer='B')])
            db.execute('UPDATE users SET is_admin=1');db.commit()
        response=self.client.get('/admin/import')
        self.assertEqual(response.status_code,200,response.data)
        self.assertIn('待核验'.encode(),response.data)
        self.assertIn('需要人工检查的题'.encode(),response.data)
        self.assertIn('乙'.encode(),response.data)

    def test_meaningful_search_year_negation_and_option_changes_stay_distinct(self):
        rows=[item('wireless netw*'),item('wireless net*'),item('GB/T 7714-2015'),item('GB/T 7714-2025'),
              item('选择正确的是'),item('选择不正确的是'),item('搜索 "heart failure"'),item('搜索 "heartfailure"'),
              item('公式',options=['^%','^p']),item('公式',options=['*','^p']),
              item('期刊',options=['AI=novelty','甲']),item('期刊',options=['AI-novelty','甲']),
              item('函数 mid()'),item('函数 mid'),item('机器 学习'),item('机器学习'),
              item('检索式：图书?'),item('检索式：图书')]
        with self.app.app_context():
            self.assertEqual(import_rows(get_db(),rows)['added'],len(rows))
            self.assertEqual(question_count(),len(rows))

    def test_literal_html_entities_and_quoted_html_code_are_not_display_markup(self):
        rows=[item('字符串代码题',answer='B',options=['"<br>"','"abc"']),
              item('字符串代码题',answer='B',options=['""','"abc"']),
              item('字符串代码题',answer='B',options=['" "','"abc"']),
              item('无引号代码题',options=['甲<br>乙','abc']),
              item('无引号代码题',options=['甲 乙','abc']),
              item('实体原文代码题',options=['&lt;br&gt;','abc']),
              item('实体原文代码题',options=['<br>','abc']),
              item('<p>题干标签原文</p>'),item('题干标签原文')]
        with self.app.app_context():
            self.assertEqual(import_rows(get_db(),rows)['added'],len(rows))
            self.assertEqual(question_count(),len(rows))

    def assert_serialized_refresh(self, commit_import):
        import distillation
        first,second=reviewed_fixture()[:2]
        with self.app.app_context():import_rows(get_db(),[first])
        snapshot_read=threading.Event();release=threading.Event();b_started=threading.Event();b_done=threading.Event()
        errors=[]
        original_init=distillation.QuestionMatcher.__init__
        original_keys=distillation.comparison_keys
        paused=False

        def pause():
            nonlocal paused
            if threading.current_thread().name=='dedup-race-a' and not paused:
                paused=True;snapshot_read.set()
                if not release.wait(5):raise AssertionError('Timed out releasing read snapshot')

        def wrapped_init(matcher,db):
            original_init(matcher,db)
            if commit_import:pause()

        def wrapped_keys(row,mark):
            result=original_keys(row,mark)
            if not commit_import:pause()
            return result

        def worker(first_worker):
            db=sqlite3.connect(self.config['DATABASE'],timeout=5);db.row_factory=sqlite3.Row
            try:
                if first_worker:
                    if commit_import:import_rows(db,[first])
                    else:distillation.refresh_duplicates(db);db.commit()
                else:
                    b_started.set();import_rows(db,[second]);b_done.set()
            except BaseException as exc:errors.append(exc)
            finally:db.close()

        with patch.object(distillation.QuestionMatcher,'__init__',wrapped_init),patch.object(distillation,'comparison_keys',wrapped_keys):
            a=threading.Thread(target=worker,args=(True,),name='dedup-race-a')
            b=threading.Thread(target=worker,args=(False,),name='dedup-race-b')
            a.start()
            self.assertTrue(snapshot_read.wait(3))
            b.start();self.assertTrue(b_started.wait(3))
            committed_during_old_snapshot=b_done.wait(.25)
            release.set();a.join(5);b.join(5)
        self.assertFalse(a.is_alive() or b.is_alive())
        self.assertEqual(errors,[])
        self.assertFalse(committed_during_old_snapshot,'Concurrent import committed while an alias refresh used an older read snapshot')
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM questions').fetchone()[0],2)
            self.assertEqual(question_count(),1)

    def test_refresh_locks_before_reading_question_snapshot(self):
        self.assert_serialized_refresh(False)

    def test_all_duplicate_commit_locks_before_reading_matcher_snapshot(self):
        self.assert_serialized_refresh(True)

    def test_new_round_and_browsing_use_the_effective_bank_and_alias_favorite_is_visible(self):
        with self.app.app_context():
            db=get_db()
            import_rows(db,reordered_reviewed_pair())
            ids=[r[0] for r in db.execute('SELECT id FROM questions ORDER BY id')]
            uid=db.execute('SELECT id FROM users').fetchone()[0]
            db.execute('INSERT INTO favorite_questions VALUES(?,?,1)',(uid,ids[1]));db.commit()
        state=self.client.post('/api/drill/start',json={'mode':'all'}).json
        self.assertEqual(state['bank_count'],1)
        self.assertEqual(state['round']['total'],1)
        self.assertEqual(state['round']['question']['id'],ids[0])
        self.assertTrue(state['round']['question']['favorited'])
        self.assertEqual(self.client.get('/api/question-bank').json['total'],1)
        self.assertEqual(self.client.get(f'/api/favorites/{ids[1]}').status_code,200)
        self.client.delete(f'/api/favorites/{ids[0]}')
        self.assertFalse(self.client.get('/api/drill/current').json['round']['question']['favorited'])

    def test_wrong_round_has_one_canonical_question_and_correct_answer_masters_every_alias(self):
        with self.app.app_context():
            db=get_db()
            import_rows(db,reordered_reviewed_pair())
            ids=[r[0] for r in db.execute('SELECT id FROM questions ORDER BY id')]
            uid=db.execute('SELECT id FROM users').fetchone()[0]
            for index,qid in enumerate(ids):
                db.execute('INSERT INTO wrong_questions(user_id,question_id,wrong_count,first_wrong_at,last_wrong_at,last_wrong_answer) VALUES(?,?,1,1,?,?)',
                    (uid,qid,index+2,json.dumps(['B'] if index==0 else ['A'])))
            db.commit()
        book=self.client.get('/api/drill/wrongs').json
        self.assertEqual(book['total'],1)
        self.assertEqual(book['stats'],{'total':1,'active':1,'mastered':0})
        self.assertEqual(book['items'][0]['wrong_count'],2)
        self.assertEqual(book['items'][0]['question_id'],ids[1])
        self.assertEqual(book['items'][0]['last_wrong_answer'],['A'])
        state=self.client.post('/api/drill/start',json={'mode':'wrong'}).json['round']
        self.assertEqual(state['total'],1)
        self.assertEqual(state['question']['id'],ids[0])
        response=self.client.post(f"/api/drill/{state['id']}/answer",json={'index':0,'answer':['A']})
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(self.client.get('/api/drill/wrongs').json['total'],0)
        with self.app.app_context():
            rows=get_db().execute('SELECT * FROM wrong_questions').fetchall()
            self.assertEqual(len(rows),2)
            self.assertTrue(all(row['mastered_at'] is not None for row in rows))
        # A later wrong answer reactivates all aliases but keeps both histories.
        state=self.client.post('/api/drill/start',json={'mode':'all'}).json['round']
        self.client.post(f"/api/drill/{state['id']}/answer",json={'index':0,'answer':['B']})
        self.assertEqual(self.client.get('/api/drill/wrongs').json['stats']['active'],1)
        with self.app.app_context():
            self.assertTrue(all(row[0] is None for row in get_db().execute('SELECT mastered_at FROM wrong_questions')))

    def test_live_round_keeps_current_draft_answered_history_and_future_drafts(self):
        with self.app.app_context():
            db=get_db();uid=db.execute('SELECT id FROM users').fetchone()[0]
            triple=reviewed_fixture(3)
            pair=reviewed_fixture(exclude=[fingerprint(row) for row in triple])
            ids=[insert_legacy(db,x) for x in [triple[0],triple[1],pair[0],pair[1],triple[2]]]
            rid=db.execute("INSERT INTO drill_rounds(user_id,mode,round_number,started_at,current_position) VALUES(?,'all',1,1,1)",(uid,)).lastrowid
            for pos,qid in enumerate(ids):
                db.execute('INSERT INTO drill_items(round_id,position,question_id,draft_answer,answer,is_correct,answered_at) VALUES(?,?,?,?,?,?,?)',
                    (rid,pos,qid,'["B"]' if pos in (1,4) else '[]','["A"]' if pos==0 else None,1 if pos==0 else None,2 if pos==0 else None))
            db.execute('INSERT INTO favorite_questions VALUES(?,?,1)',(uid,ids[1]))
            aid=db.execute("INSERT INTO attempts(kind,user_id,started_at,submitted_at,score) VALUES('personal',?,1,2,2)",(uid,)).lastrowid
            db.execute('INSERT INTO attempt_questions(attempt_id,position,question_id) VALUES(?,0,?)',(aid,ids[3]))
            db.commit()
        migrated=create_app(self.config)
        with migrated.app_context():
            db=get_db()
            rows=db.execute('SELECT * FROM drill_items WHERE round_id=? ORDER BY position',(rid,)).fetchall()
            self.assertEqual([r['question_id'] for r in rows],[ids[0],ids[1],ids[2],ids[4]])
            self.assertEqual([r['position'] for r in rows],[0,1,2,3])
            self.assertEqual(rows[1]['draft_answer'],'["B"]')
            self.assertEqual(rows[3]['draft_answer'],'["B"]')
            self.assertEqual(rows[0]['answered_at'],2)
            self.assertEqual(db.execute('SELECT current_position FROM drill_rounds').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT question_id FROM favorite_questions').fetchone()[0],ids[1])
            self.assertEqual(db.execute('SELECT question_id FROM attempt_questions').fetchone()[0],ids[3])


if __name__=='__main__':unittest.main()
