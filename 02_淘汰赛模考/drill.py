"""Persistent per-user question rounds and wrong-answer history."""
import json
import random
import time

from flask import Blueprint, abort, jsonify, render_template, request, session
from distillation import group_ids


SCHEMA = '''
CREATE TABLE IF NOT EXISTS drill_rounds(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  mode TEXT NOT NULL CHECK(mode IN ('all','wrong')), round_number INTEGER NOT NULL,
  started_at INTEGER NOT NULL, finished_at INTEGER, current_position INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS drill_one_live_round ON drill_rounds(user_id,mode) WHERE finished_at IS NULL;
CREATE INDEX IF NOT EXISTS drill_user_history ON drill_rounds(user_id,mode,id DESC);
CREATE TABLE IF NOT EXISTS drill_items(
  round_id INTEGER NOT NULL REFERENCES drill_rounds(id), position INTEGER NOT NULL,
  question_id INTEGER NOT NULL REFERENCES questions(id), draft_answer TEXT NOT NULL DEFAULT '[]',
  answer TEXT, is_correct INTEGER, answered_at INTEGER,
  PRIMARY KEY(round_id,position), UNIQUE(round_id,question_id));
CREATE TABLE IF NOT EXISTS wrong_questions(
  user_id INTEGER NOT NULL REFERENCES users(id), question_id INTEGER NOT NULL REFERENCES questions(id),
  wrong_count INTEGER NOT NULL DEFAULT 1, first_wrong_at INTEGER NOT NULL, last_wrong_at INTEGER NOT NULL,
  last_wrong_answer TEXT NOT NULL, mastered_at INTEGER,
  PRIMARY KEY(user_id,question_id));
CREATE INDEX IF NOT EXISTS wrong_user_status ON wrong_questions(user_id,mastered_at,last_wrong_at DESC);
'''


def register_drill(app, get_db, login_required):
    with app.app_context():
        get_db().executescript(SCHEMA)
        get_db().commit()
    bp = Blueprint('drill', __name__)

    def error(message, status=400):
        return jsonify(error=message), status

    def body():
        value = request.get_json(silent=True)
        return value if isinstance(value, dict) else {}

    def get_round(rid):
        row = get_db().execute('SELECT * FROM drill_rounds WHERE id=?', (rid,)).fetchone()
        if row is None:
            abort(404)
        if row['user_id'] != session['uid']:
            abort(403)
        return row

    def wrong_groups():
        rows = get_db().execute('''SELECT w.*,q.type,q.stem,q.options,q.answer correct,q.explanation,q.module,q.source,
          COALESCE(d.canonical_id,w.question_id) canonical_id
          FROM wrong_questions w JOIN questions q ON q.id=w.question_id
          LEFT JOIN question_duplicates d ON d.alias_id=w.question_id
          WHERE w.user_id=? ORDER BY w.last_wrong_at DESC,w.question_id DESC''', (session['uid'],)).fetchall()
        grouped = {}
        for row in rows:
            root = row['canonical_id']
            if root not in grouped:
                grouped[root] = dict(row)
                continue
            item = grouped[root]
            item['wrong_count'] += row['wrong_count']
            item['first_wrong_at'] = min(item['first_wrong_at'],row['first_wrong_at'])
            if row['mastered_at'] is None:
                item['mastered_at'] = None
            elif item['mastered_at'] is not None:
                item['mastered_at'] = max(item['mastered_at'],row['mastered_at'])
        return list(grouped.values())

    def wrong_stats():
        groups = wrong_groups()
        active = sum(row['mastered_at'] is None for row in groups)
        return {'total':len(groups), 'active':active, 'mastered':len(groups)-active}

    def payload(row):
        counts = get_db().execute('''SELECT COUNT(*) total, COUNT(answered_at) answered_count,
          COALESCE(SUM(is_correct=1),0) correct_count,
          COALESCE(SUM(is_correct=0),0) wrong_count FROM drill_items WHERE round_id=?''', (row['id'],)).fetchone()
        item = get_db().execute('''SELECT d.*,q.type,q.stem,q.options,q.answer correct,q.explanation,q.module,q.source
          FROM drill_items d JOIN questions q ON q.id=d.question_id WHERE d.round_id=? AND d.position=?''',
          (row['id'], row['current_position'])).fetchone()
        question = None
        if item:
            submitted = item['answered_at'] is not None
            family = group_ids(get_db(), item['question_id'])
            placeholders = ','.join('?' for _ in family)
            question = {'id':item['question_id'], 'type':item['type'], 'stem':item['stem'],
                        'options':json.loads(item['options']), 'module':item['module'],
                        'selected':json.loads(item['answer'] if submitted else item['draft_answer']),
                        'submitted':submitted,
                        'favorited':get_db().execute('SELECT 1 FROM favorite_questions WHERE user_id=? AND question_id IN ('+placeholders+')',
                                                    (session['uid'],*family)).fetchone() is not None}
            if submitted:
                question.update(correct=json.loads(item['correct']), is_correct=bool(item['is_correct']),
                                explanation=item['explanation'], source=item['source'], answered_at=item['answered_at'])
        return {'id':row['id'], 'mode':row['mode'], 'round_number':row['round_number'],
                'current_position':row['current_position'], 'started_at':row['started_at'],
                'finished':row['finished_at'] is not None, 'finished_at':row['finished_at'],
                **dict(counts), 'question':question}

    def state(row=None):
        return jsonify(round=payload(row) if row is not None else None,
                       bank_count=get_db().execute('SELECT COUNT(*) FROM active_questions').fetchone()[0],
                       wrong_book=wrong_stats())

    def current_item(row):
        return get_db().execute('''SELECT d.*,q.type,q.options,q.answer correct FROM drill_items d
          JOIN questions q ON q.id=d.question_id WHERE d.round_id=? AND d.position=?''',
          (row['id'], row['current_position'])).fetchone()

    def valid_choices(item, chosen, allow_empty=False):
        keys = {option['key'] for option in json.loads(item['options'])}
        return (isinstance(chosen,list) and (allow_empty or bool(chosen))
                and all(isinstance(value,str) and value in keys for value in chosen)
                and len(set(chosen))==len(chosen) and (item['type']=='multi' or len(chosen)<=1))

    @bp.get('/drill')
    @login_required
    def drill_page():
        mode=request.args.get('mode','all')
        if mode not in ('all','wrong'):
            abort(400)
        return render_template('drill.html', drill_mode=mode)

    @bp.get('/wrong-book')
    @login_required
    def wrong_book_page():
        return render_template('wrong_book.html')

    @bp.get('/api/drill/current')
    @login_required
    def current():
        mode=request.args.get('mode','all')
        if mode not in ('all','wrong'):
            return error('刷题模式无效')
        row=get_db().execute('SELECT * FROM drill_rounds WHERE user_id=? AND mode=? ORDER BY id DESC LIMIT 1',
                             (session['uid'],mode)).fetchone()
        return state(row)

    @bp.post('/api/drill/start')
    @login_required
    def start():
        mode=body().get('mode','all')
        if mode not in ('all','wrong'):
            return error('刷题模式无效')
        db=get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT * FROM drill_rounds WHERE user_id=? AND mode=? AND finished_at IS NULL',
                                (session['uid'],mode)).fetchone()
            if existing is not None:
                return state(existing)
            if mode=='all':
                ids=[row[0] for row in db.execute('SELECT id FROM active_questions ORDER BY id')]
            else:
                ids=sorted(row['canonical_id'] for row in wrong_groups() if row['mastered_at'] is None)
            if not ids:
                return error('题库为空，请先导入题目' if mode=='all' else '当前没有待复习错题')
            random.shuffle(ids)
            number=db.execute('SELECT COALESCE(MAX(round_number),0)+1 FROM drill_rounds WHERE user_id=? AND mode=?',
                              (session['uid'],mode)).fetchone()[0]
            cursor=db.execute('INSERT INTO drill_rounds(user_id,mode,round_number,started_at) VALUES(?,?,?,?)',
                              (session['uid'],mode,number,int(time.time())))
            rid=cursor.lastrowid
            db.executemany('INSERT INTO drill_items(round_id,position,question_id) VALUES(?,?,?)',
                           [(rid,index,qid) for index,qid in enumerate(ids)])
            return state(get_round(rid))

    @bp.post('/api/drill/<int:rid>/draft')
    @login_required
    def save_draft(rid):
        data=body();db=get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            row=get_round(rid)
            if type(data.get('index')) is not int:
                return error('题目位置无效')
            if data['index']!=row['current_position'] or row['finished_at'] is not None:
                return error('题目已切换，请刷新后继续',409)
            item=current_item(row)
            if item['answered_at'] is not None:
                return error('本题已提交，不能修改',409)
            if not valid_choices(item,data.get('answer'),allow_empty=True):
                return error('答案选项无效')
            db.execute('UPDATE drill_items SET draft_answer=? WHERE round_id=? AND position=?',
                       (json.dumps(sorted(data['answer'])),rid,row['current_position']))
            return jsonify(saved=True)

    @bp.post('/api/drill/<int:rid>/answer')
    @login_required
    def submit_answer(rid):
        data=body();db=get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            row=get_round(rid)
            if type(data.get('index')) is not int:
                return error('题目位置无效')
            if data['index']!=row['current_position']:
                return error('题目已切换，请刷新后继续',409)
            item=current_item(row)
            if not valid_choices(item,data.get('answer')):
                return error('请先选择有效答案')
            chosen=sorted(data['answer'])
            if item['answered_at'] is not None:
                if chosen!=sorted(json.loads(item['answer'])):
                    return error('本题已提交，不能修改答案',409)
                return state(row)
            timestamp=int(time.time())
            correct=set(chosen)==set(json.loads(item['correct']))
            encoded=json.dumps(chosen)
            db.execute('''UPDATE drill_items SET answer=?,draft_answer=?,is_correct=?,answered_at=?
              WHERE round_id=? AND position=?''', (encoded,encoded,int(correct),timestamp,rid,row['current_position']))
            if not correct:
                db.execute('''INSERT INTO wrong_questions(user_id,question_id,wrong_count,first_wrong_at,last_wrong_at,last_wrong_answer)
                  VALUES(?,?,1,?,?,?) ON CONFLICT(user_id,question_id) DO UPDATE SET
                  wrong_count=wrong_questions.wrong_count+1,last_wrong_at=excluded.last_wrong_at,
                  last_wrong_answer=excluded.last_wrong_answer,mastered_at=NULL''',
                  (session['uid'],item['question_id'],timestamp,timestamp,encoded))
            family=group_ids(db,item['question_id'])
            placeholders=','.join('?' for _ in family)
            db.execute('UPDATE wrong_questions SET mastered_at=? WHERE user_id=? AND question_id IN ('+placeholders+')',
                       (timestamp if correct else None,session['uid'],*family))
            remaining=db.execute('SELECT COUNT(*) FROM drill_items WHERE round_id=? AND answered_at IS NULL',(rid,)).fetchone()[0]
            if not remaining:
                db.execute('UPDATE drill_rounds SET finished_at=? WHERE id=?',(timestamp,rid))
            return state(get_round(rid))

    @bp.post('/api/drill/<int:rid>/next')
    @login_required
    def next_question(rid):
        data=body();db=get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            row=get_round(rid)
            if type(data.get('index')) is not int or data['index']!=row['current_position']:
                return error('题目已切换，请刷新后继续',409)
            if current_item(row)['answered_at'] is None:
                return error('请先提交本题答案，再进入下一题')
            if row['finished_at'] is None:
                db.execute('UPDATE drill_rounds SET current_position=current_position+1 WHERE id=?',(rid,))
            return state(get_round(rid))

    @bp.get('/api/drill/wrongs')
    @login_required
    def wrongs():
        status=request.args.get('status','active')
        if status not in ('all','active','mastered'):
            return error('错题筛选条件无效')
        try:
            page=int(request.args.get('page','1'))
            if not 1<=page<=1000000:raise ValueError()
        except ValueError:
            return error('页码无效')
        per_page=20
        rows=[row for row in wrong_groups() if status=='all' or (row['mastered_at'] is None)==(status=='active')]
        total=len(rows)
        rows=rows[(page-1)*per_page:page*per_page]
        items=[]
        for row in rows:
            items.append({'question_id':row['question_id'],'type':row['type'],'stem':row['stem'],
                'options':json.loads(row['options']),'correct':json.loads(row['correct']),
                'last_wrong_answer':json.loads(row['last_wrong_answer']),'wrong_count':row['wrong_count'],
                'first_wrong_at':row['first_wrong_at'],'last_wrong_at':row['last_wrong_at'],
                'mastered_at':row['mastered_at'],'explanation':row['explanation'],
                'module':row['module'],'source':row['source']})
        return jsonify(items=items,total=total,page=page,per_page=per_page,stats=wrong_stats())

    app.register_blueprint(bp)
