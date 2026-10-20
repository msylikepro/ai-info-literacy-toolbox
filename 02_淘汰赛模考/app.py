import json
import os
import random
import secrets
import sqlite3
import time
from pathlib import Path
from functools import wraps

from flask import Flask, abort, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from importer import import_rows, inspect_rows, parse_file
from drill import register_drill
from favorites import register_favorites
from question_bank import register_question_bank
from distillation import ensure_schema as ensure_distillation_schema, refresh_duplicates
from exam_rules import defaults, validate_settings, outcome, total, KINDS, LABELS, DEFAULT_TIMING, validate_timing

ROOT = Path(__file__).resolve().parent


def now():
    return int(time.time())


QUESTION_MIX = {'single': 6, 'multi': 2, 'judge': 2}


def score_answer(kind, chosen, correct, legacy=False, correct_points=2):
    if not chosen:
        return 0
    if legacy:
        return (2 if kind == 'team' else 1) if set(chosen) == set(correct) else -0.5
    return correct_points if set(chosen) == set(correct) else -1


def ranking_key(result):
    return (-result['score'], result['duration_seconds'])


def get_db():
    if 'db' not in g:
        db = sqlite3.connect(current_app.config['DATABASE'], timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=30000')
        g.db = db
    return g.db


def login_required(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if not session.get('uid'):
            if request.path.startswith('/api/'):
                abort(401)
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return inner


def admin_required(fn):
    @wraps(fn)
    @login_required
    def inner(*args, **kwargs):
        if not user()['is_admin']:
            abort(403)
        return fn(*args, **kwargs)
    return inner


def user():
    return get_db().execute('SELECT * FROM users WHERE id=?', (session['uid'],)).fetchone()


def team_for(uid):
    return get_db().execute('SELECT t.* FROM teams t JOIN team_members m ON m.team_id=t.id WHERE m.user_id=?', (uid,)).fetchone()


def question_count():
    return get_db().execute('SELECT COUNT(*) FROM active_questions').fetchone()[0]


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(DATABASE=str(ROOT / 'data' / 'platform.db'), SECRET_KEY=None,
                      MAX_CONTENT_LENGTH=10 * 1024 * 1024, SEED=True)
    if config:
        app.config.update(config)
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    if not app.config['SECRET_KEY']:
        keyfile = ROOT / 'data' / '.secret_key'
        if not keyfile.exists():
            keyfile.write_text(secrets.token_hex(32), encoding='utf-8')
        app.config['SECRET_KEY'] = keyfile.read_text(encoding='utf-8')
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_HTTPONLY'] = True

    @app.before_request
    def setup_request():
        g.app = app
        if request.method in ('POST', 'PUT', 'DELETE'):
            origin = request.headers.get('Origin')
            if origin and origin.rstrip('/').lower() != request.host_url.rstrip('/').lower():
                abort(403)

    @app.teardown_appcontext
    def close_db(exc):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    with app.app_context():
        g.app = app
        db = get_db()
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS teams(id INTEGER PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS team_members(team_id INTEGER NOT NULL REFERENCES teams(id), user_id INTEGER NOT NULL UNIQUE REFERENCES users(id), PRIMARY KEY(team_id,user_id));
        CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
          type TEXT NOT NULL, stem TEXT NOT NULL, options TEXT NOT NULL, answer TEXT NOT NULL,
          source TEXT, module TEXT, original_id TEXT, explanation TEXT);
        CREATE TABLE IF NOT EXISTS simulations(id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL REFERENCES teams(id),
          started_at INTEGER NOT NULL, deadline INTEGER NOT NULL, team_attempt_id INTEGER);
        CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, user_id INTEGER REFERENCES users(id),
          team_id INTEGER REFERENCES teams(id), simulation_id INTEGER REFERENCES simulations(id),
          started_at INTEGER, deadline INTEGER, submitted_at INTEGER, score REAL,
          answers TEXT NOT NULL DEFAULT '{}', correct_points INTEGER NOT NULL DEFAULT 2,
          current_position INTEGER NOT NULL DEFAULT 0,
          question_started_at INTEGER);
        CREATE TABLE IF NOT EXISTS attempt_questions(attempt_id INTEGER NOT NULL REFERENCES attempts(id),
          position INTEGER NOT NULL, question_id INTEGER NOT NULL REFERENCES questions(id),
          duration_seconds INTEGER, PRIMARY KEY(attempt_id,position));
        CREATE TABLE IF NOT EXISTS exam_settings(user_id INTEGER PRIMARY KEY REFERENCES users(id), rules_json TEXT NOT NULL);
        ''')
        if not any(col['name'] == 'current_position' for col in db.execute('PRAGMA table_info(attempts)')):
            db.execute('ALTER TABLE attempts ADD COLUMN current_position INTEGER NOT NULL DEFAULT 0')
        if not any(col['name'] == 'question_started_at' for col in db.execute('PRAGMA table_info(attempts)')):
            db.execute('ALTER TABLE attempts ADD COLUMN question_started_at INTEGER')
        if not any(col['name'] == 'correct_points' for col in db.execute('PRAGMA table_info(attempts)')):
            db.execute('ALTER TABLE attempts ADD COLUMN correct_points INTEGER NOT NULL DEFAULT 2')
        if not any(col['name'] == 'rules_json' for col in db.execute('PRAGMA table_info(attempts)')):
            db.execute('ALTER TABLE attempts ADD COLUMN rules_json TEXT')
        for table,column in (('attempts','time_limit_minutes'),('simulations','personal_minutes'),('simulations','team_minutes')):
            if not any(col['name']==column for col in db.execute('PRAGMA table_info('+table+')')):
                db.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' INTEGER')
        if not any(col['name']=='timing_json' for col in db.execute('PRAGMA table_info(exam_settings)')):
            db.execute('ALTER TABLE exam_settings ADD COLUMN timing_json TEXT')
        if not any(col['name'] == 'duration_seconds' for col in db.execute('PRAGMA table_info(attempt_questions)')):
            db.execute('ALTER TABLE attempt_questions ADD COLUMN duration_seconds INTEGER')
        ensure_distillation_schema(db)
        db.commit()
        if app.config['SEED'] and question_count() == 0:
            for filename, label in [('source_questions.json', '公开仓库 89757-creater/ai-info-literacy-quiz（未独立核验）'),
                                    ('source_bank.json', '公开仓库 Ziv-ZHI/ai-infolit-competition（未独立核验）')]:
                path = ROOT / 'data' / filename
                if path.exists():
                    import_rows(db, parse_file(filename, path.read_bytes()), label)
        refresh_duplicates(db)
        db.commit()
        if not app.config.get('TESTING') and not db.execute('SELECT 1 FROM users WHERE is_admin=1').fetchone():
            password = os.environ.get('ADMIN_PASSWORD') or secrets.token_urlsafe(12)
            db.execute('INSERT INTO users(username,password_hash,is_admin) VALUES(?,?,1)', ('admin', generate_password_hash(password)))
            db.commit()
            if not os.environ.get('ADMIN_PASSWORD'):
                credentials = ROOT / 'data' / 'admin_credentials.txt'
                credentials.write_text('管理员用户名：admin\n管理员密码：' + password + '\n首次登录后请妥善保管。\n', encoding='utf-8')

    def response_error(message, status=400):
        return jsonify(error=message), status

    def settings_for(uid):
        saved=get_db().execute('SELECT rules_json FROM exam_settings WHERE user_id=?',(uid,)).fetchone()
        return json.loads(saved['rules_json']) if saved else {mode:defaults(mode) for mode in ('personal','team')}

    def timing_for(uid):
        saved=get_db().execute('SELECT timing_json FROM exam_settings WHERE user_id=?',(uid,)).fetchone()
        return json.loads(saved['timing_json']) if saved and saved['timing_json'] else dict(DEFAULT_TIMING)

    @app.route('/api/exam-timing',methods=['GET','POST'])
    @login_required
    def exam_timing():
        if request.method=='GET':
            return jsonify(timing_for(session['uid']))
        try:timing=validate_timing(request.get_json(silent=True))
        except ValueError as error:return response_error(str(error))
        get_db().execute('INSERT INTO exam_settings(user_id,rules_json,timing_json) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET timing_json=excluded.timing_json',
                         (session['uid'],json.dumps(settings_for(session['uid'])),json.dumps(timing)))
        get_db().commit()
        return jsonify(timing)

    def deadline_for(start,minutes,cap=None):
        deadline=start+minutes*60 if minutes else None
        return min(deadline,cap) if deadline is not None and cap else (cap or deadline)

    def simulation_expired(sim):
        return bool(sim['deadline'] and now()>=sim['deadline'])

    def team_minutes_for(sim):
        return sim['team_minutes'] if sim['team_minutes'] is not None else (30 if sim['deadline']-sim['started_at']==2400 else 15)

    @app.route('/api/exam-settings',methods=['GET','POST'])
    @login_required
    def exam_settings():
        if request.method=='GET':
            return jsonify(settings_for(session['uid']))
        try:
            rules=validate_settings(request.get_json(silent=True))
        except ValueError as error:
            return response_error(str(error))
        get_db().execute('INSERT INTO exam_settings(user_id,rules_json) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET rules_json=excluded.rules_json',
                         (session['uid'],json.dumps(rules)))
        get_db().commit()
        return jsonify(rules)

    def rules_for(row,questions=None):
        if row['rules_json']:
            return json.loads(row['rules_json'])
        questions=questions if questions is not None else questions_for(row['id'])
        mode='team' if row['kind'] in ('team','sim_team','training_team') else 'personal'
        rules=defaults(mode)
        legacy=len(questions)==20
        for kind,rule in rules.items():
            rule['count']=sum(q['type']==kind for q in questions)
            rule['correct']=(2 if mode=='team' else 1) if legacy else row['correct_points']
            rule['wrong']=-0.5 if legacy else -1
        return rules

    def maximum(row,questions=None):
        return total(rule['correct'] for rule in rules_for(row,questions).values() for _ in range(rule['count']))

    def unstarted_team_expired(sim):
        row=get_db().execute('SELECT * FROM attempts WHERE id=?',(sim['team_attempt_id'],)).fetchone()
        if row['started_at'] is None:
            points=total(rule['unanswered'] for rule in rules_for(row).values() for _ in range(rule['count']))
            get_db().execute('UPDATE attempts SET started_at=?,deadline=?,submitted_at=?,score=? WHERE id=? AND started_at IS NULL',
                             (sim['deadline'],sim['deadline'],sim['deadline'],points,row['id']))
            get_db().commit()

    def get_attempt(aid):
        row = get_db().execute('SELECT * FROM attempts WHERE id=?', (aid,)).fetchone()
        if not row:
            abort(404)
        if row['user_id']:
            if row['user_id'] != session['uid']:
                abort(403)
        elif not get_db().execute('SELECT 1 FROM team_members WHERE team_id=? AND user_id=?', (row['team_id'], session['uid'])).fetchone():
            abort(403)
        if row['started_at'] is None:
            abort(403)
        expire(row)
        return get_db().execute('SELECT * FROM attempts WHERE id=?', (aid,)).fetchone()

    def questions_for(aid):
        return get_db().execute('''SELECT q.*,aq.duration_seconds FROM questions q JOIN attempt_questions aq ON aq.question_id=q.id
                                  WHERE aq.attempt_id=? ORDER BY aq.position''', (aid,)).fetchall()

    def finalize(row, at=None):
        if row['submitted_at'] is not None or row['started_at'] is None:
            return
        ended = min(at or now(), row['deadline']) if row['deadline'] is not None else (at or now())
        if row['question_started_at'] is not None:
            get_db().execute('''UPDATE attempt_questions SET duration_seconds=?
                WHERE attempt_id=? AND position=? AND duration_seconds IS NULL''',
                (max(0, ended - row['question_started_at']), row['id'], row['current_position']))
        answers = json.loads(row['answers'])
        questions = questions_for(row['id'])
        rules=rules_for(row,questions)
        score = total(rules[q['type']][outcome(answers.get(str(i),[]),json.loads(q['answer']))]
                      for i,q in enumerate(questions))
        get_db().execute('UPDATE attempts SET submitted_at=?,score=? WHERE id=? AND submitted_at IS NULL',
                         (ended, score, row['id']))
        get_db().commit()

    def expire(row):
        if row['submitted_at'] is None and row['deadline'] is not None and now() >= row['deadline']:
            finalize(row, row['deadline'])

    def make_attempt(kind, ids, uid=None, team_id=None, sim_id=None, start=None, deadline=None, rules=None, minutes=None):
        db = get_db()
        correct_points = 4 if kind in ('team', 'sim_team', 'training_team') else 2
        cur = db.execute('''INSERT INTO attempts(kind,user_id,team_id,simulation_id,started_at,deadline,question_started_at,correct_points,rules_json,time_limit_minutes)
                            VALUES(?,?,?,?,?,?,?,?,?,?)''', (kind, uid, team_id, sim_id, start, deadline, start, correct_points,json.dumps(rules) if rules else None,minutes))
        aid = cur.lastrowid
        db.executemany('INSERT INTO attempt_questions(attempt_id,position,question_id) VALUES(?,?,?)',
                       [(aid, i, qid) for i, qid in enumerate(ids)])
        return aid

    def chosen_papers(profiles):
        pools = {}
        missing = []
        for kind in KINDS:
            ids = [r[0] for r in get_db().execute('SELECT id FROM active_questions WHERE type=?', (kind,))]
            needed = sum(profile[kind]['count'] for profile in profiles)
            if len(ids) < needed:
                label = LABELS[kind]
                missing.append(f'{label}需 {needed} 题、现有 {len(ids)} 题')
            else:
                pools[kind] = random.sample(ids, needed)
        if missing:
            return None, '题库不足：' + '；'.join(missing)
        papers = []
        offsets={kind:0 for kind in KINDS}
        for profile in profiles:
            paper = []
            for kind in KINDS:
                count=profile[kind]['count'];offset=offsets[kind]
                paper.extend(pools[kind][offset:offset+count]);offsets[kind]+=count
            papers.append(paper)
        return papers, None

    def attempt_payload(row):
        finished = row['submitted_at'] is not None
        questions = questions_for(row['id'])
        if not finished and row['current_position'] >= len(questions):
            finalize(row)
            row = get_db().execute('SELECT * FROM attempts WHERE id=?', (row['id'],)).fetchone()
            finished = True
        answers = json.loads(row['answers'])
        kind = 'team' if row['kind'] in ('team', 'sim_team', 'training_team') else 'personal'
        rules=rules_for(row,questions)
        items = []
        for i, q in enumerate(questions):
            if not finished and i != row['current_position']:
                continue
            item = {'index': i, 'type': q['type'], 'stem': q['stem'], 'options': json.loads(q['options']),
                    'answer': answers.get(str(i), []), 'module': q['module']}
            if finished:
                correct = json.loads(q['answer'])
                status=outcome(item['answer'],correct)
                item.update(correct=correct, explanation=q['explanation'], source=q['source'],
                            original_id=q['original_id'], points=rules[q['type']][status],outcome=status,
                            duration_seconds=q['duration_seconds'])
            items.append(item)
        progress = [('answered' if answers.get(str(i)) else 'skipped') if i < row['current_position'] else
                    ('current' if i == row['current_position'] else 'pending') for i in range(len(questions))]
        return {'id': row['id'], 'kind': row['kind'], 'simulation_id': row['simulation_id'],
                'started_at': row['started_at'], 'deadline': row['deadline'],
                'time_limit_minutes':row['time_limit_minutes'] if row['time_limit_minutes'] is not None else (0 if row['deadline'] is None else max(0,row['deadline']-row['started_at'])/60),
                'remaining_seconds': None if row['deadline'] is None else (max(0, row['deadline'] - now()) if not finished else 0),
                'submitted_at': row['submitted_at'], 'duration_seconds': row['submitted_at'] - row['started_at'] if finished else None,
                'score': row['score'] if finished else None,
                'correct_points': rules['single']['correct'],'scoring_rules':rules,
                'max_score': maximum(row,questions),
                'question_count': len(questions), 'current_position': row['current_position'],
                'progress': progress, 'questions': items}

    @app.get('/')
    def home():
        if not session.get('uid'):
            return redirect(url_for('login'))
        u = user()
        t = team_for(u['id'])
        rules=settings_for(u['id'])
        stock = {r['type']: r['n'] for r in get_db().execute('SELECT type, COUNT(*) n FROM active_questions GROUP BY type')}
        ready_personal=all(stock.get(kind,0)>=rules['personal'][kind]['count'] for kind in KINDS)
        ready_team=all(stock.get(kind,0)>=rules['team'][kind]['count'] for kind in KINDS)
        personal_count=sum(rule['count'] for rule in rules['personal'].values())
        team_count=sum(rule['count'] for rule in rules['team'].values())
        members = [] if not t else get_db().execute('SELECT u.username FROM users u JOIN team_members m ON u.id=m.user_id WHERE m.team_id=? ORDER BY m.user_id', (t['id'],)).fetchall()
        sim_papers = len(members) + 1
        ready_sim=all(stock.get(kind,0)>=rules['personal'][kind]['count']*len(members)+rules['team'][kind]['count'] for kind in KINDS)
        own = get_db().execute('SELECT * FROM attempts WHERE user_id=? ORDER BY id DESC', (u['id'],)).fetchall()
        shared = [] if not t else get_db().execute('''SELECT a.*,(SELECT COUNT(*) FROM attempt_questions WHERE attempt_id=a.id) question_count
          FROM attempts a WHERE a.team_id=? AND a.kind IN ("team","sim_team","training_team") AND a.started_at IS NOT NULL ORDER BY a.id DESC''', (t['id'],)).fetchall()
        sims = [] if not t else get_db().execute('SELECT * FROM simulations WHERE team_id=? ORDER BY id DESC', (t['id'],)).fetchall()
        for row in own + shared:
            expire(row)
        own = get_db().execute('SELECT * FROM attempts WHERE user_id=? ORDER BY id DESC', (u['id'],)).fetchall()
        shared = [] if not t else get_db().execute('''SELECT a.*,(SELECT COUNT(*) FROM attempt_questions WHERE attempt_id=a.id) question_count
          FROM attempts a WHERE a.team_id=? AND a.kind IN ("team","sim_team","training_team") AND a.started_at IS NOT NULL ORDER BY a.id DESC''', (t['id'],)).fetchall()
        own=[dict(row,max_score=maximum(row)) for row in own]
        shared=[dict(row,max_score=maximum(row)) for row in shared]
        ranked=[]
        for sim in sims:
            papers=get_db().execute('SELECT * FROM attempts WHERE simulation_id=?',(sim['id'],)).fetchall()
            if len(papers)>=2 and all(row['submitted_at'] is not None for row in papers):
                ranked.append(dict(id=sim['id'],score=total(row['score'] for row in papers),
                                   max_score=total(maximum(row) for row in papers),
                                   duration_seconds=sum(row['submitted_at']-row['started_at'] for row in papers)))
        ranked.sort(key=ranking_key)
        return render_template('home.html', u=u, team=t, members=members, own=own, shared=shared,
                               sims=sims, ranked=ranked, count=question_count(), stock=stock,
                               rules=rules,timing=timing_for(u['id']),personal_count=personal_count,team_count=team_count,
                               ready_one=ready_personal,ready_personal=ready_personal,ready_team=ready_team,
                               ready_sim=ready_sim,sim_papers=sim_papers,
                               sim_question_count=personal_count*len(members)+team_count)

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'GET':
            return render_template('auth.html', mode='register')
        name = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not 3 <= len(name) <= 30 or not 8 <= len(password) <= 128:
            flash('用户名需 3–30 字，密码需 8–128 字。')
            return redirect(url_for('register'))
        try:
            cur = get_db().execute('INSERT INTO users(username,password_hash) VALUES(?,?)', (name, generate_password_hash(password)))
            get_db().commit()
        except sqlite3.IntegrityError:
            flash('用户名已存在。')
            return redirect(url_for('register'))
        session.clear()
        session['uid'] = cur.lastrowid
        return redirect(url_for('home'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'GET':
            return render_template('auth.html', mode='login')
        row = get_db().execute('SELECT * FROM users WHERE username=?', ((request.form.get('username') or '').strip(),)).fetchone()
        if not row or not check_password_hash(row['password_hash'], request.form.get('password') or ''):
            flash('用户名或密码错误。')
            return redirect(url_for('login'))
        session.clear()
        session['uid'] = row['id']
        return redirect(url_for('home'))

    @app.post('/logout')
    @login_required
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.post('/team/create')
    @login_required
    def create_team():
        if team_for(session['uid']):
            return response_error('已加入队伍')
        name = (request.form.get('name') or '').strip()[:60]
        if not name:
            return response_error('请填写队伍名称')
        db = get_db()
        code = secrets.token_hex(4).upper()
        cur = db.execute('INSERT INTO teams(name,code) VALUES(?,?)', (name, code))
        db.execute('INSERT INTO team_members(team_id,user_id) VALUES(?,?)', (cur.lastrowid, session['uid']))
        db.commit()
        return jsonify(code=code, team_id=cur.lastrowid)

    @app.post('/team/join')
    @login_required
    def join_team():
        if team_for(session['uid']):
            return response_error('已加入队伍')
        db = get_db()
        db.execute('BEGIN IMMEDIATE')
        t = db.execute('SELECT * FROM teams WHERE code=?', ((request.form.get('code') or '').strip().upper(),)).fetchone()
        if not t:
            db.rollback()
            return response_error('邀请码无效')
        if db.execute('SELECT COUNT(*) FROM team_members WHERE team_id=?', (t['id'],)).fetchone()[0] >= 3:
            db.rollback()
            return response_error('队伍已满')
        db.execute('INSERT INTO team_members(team_id,user_id) VALUES(?,?)', (t['id'], session['uid']))
        db.commit()
        return jsonify(team_id=t['id'])

    @app.post('/practice/personal/start')
    @login_required
    def start_personal():
        rules=settings_for(session['uid'])['personal']
        papers, error = chosen_papers([rules])
        if error:
            return response_error(error)
        start = now()
        minutes=timing_for(session['uid'])['personal']
        aid = make_attempt('personal', papers[0], uid=session['uid'], start=start, deadline=deadline_for(start,minutes),rules=rules,minutes=minutes)
        get_db().commit()
        return jsonify(attempt_id=aid)

    @app.post('/practice/team/start')
    @login_required
    def start_team():
        t = team_for(session['uid'])
        if not t:
            return response_error('请先创建或加入队伍')
        rules=settings_for(session['uid'])['team']
        papers, error = chosen_papers([rules])
        if error:
            return response_error(error)
        start = now()
        minutes=timing_for(session['uid'])['team']
        aid = make_attempt('team', papers[0], team_id=t['id'], start=start, deadline=deadline_for(start,minutes),rules=rules,minutes=minutes)
        get_db().commit()
        return jsonify(attempt_id=aid)

    @app.post('/training/personal/start')
    @login_required
    def start_personal_training():
        rules=settings_for(session['uid'])['personal']
        papers, error = chosen_papers([rules])
        if error:
            return response_error(error)
        start=now();minutes=timing_for(session['uid'])['training_personal']
        aid = make_attempt('training_personal', papers[0], uid=session['uid'], start=start,deadline=deadline_for(start,minutes),rules=rules,minutes=minutes)
        get_db().commit()
        return jsonify(attempt_id=aid)

    @app.post('/training/team/start')
    @login_required
    def start_team_training():
        t = team_for(session['uid'])
        if not t:
            return response_error('请先创建或加入队伍')
        rules=settings_for(session['uid'])['team']
        papers, error = chosen_papers([rules])
        if error:
            return response_error(error)
        start=now();minutes=timing_for(session['uid'])['training_team']
        aid = make_attempt('training_team', papers[0], team_id=t['id'], start=start,deadline=deadline_for(start,minutes),rules=rules,minutes=minutes)
        get_db().commit()
        return jsonify(attempt_id=aid)

    @app.post('/simulation/start')
    @login_required
    def start_simulation():
        t = team_for(session['uid'])
        db = get_db()
        if not t:
            return response_error('请先加入队伍')
        db.execute('BEGIN IMMEDIATE')
        members = db.execute('SELECT user_id FROM team_members WHERE team_id=? ORDER BY user_id', (t['id'],)).fetchall()
        rules=settings_for(session['uid'])
        papers, error = chosen_papers([rules['personal']]*len(members)+[rules['team']])
        if error:
            db.rollback()
            return response_error(error)
        active = db.execute('SELECT * FROM simulations WHERE team_id=? ORDER BY id DESC LIMIT 1', (t['id'],)).fetchone()
        if active and active['team_attempt_id']:
            old_team = db.execute('SELECT * FROM attempts WHERE id=?', (active['team_attempt_id'],)).fetchone()
            if not simulation_expired(active) and (old_team['started_at'] is None or old_team['submitted_at'] is None):
                db.rollback()
                return response_error('队伍已有进行中的完整模拟')
        start = now()
        timing=timing_for(session['uid']);cap=deadline_for(start,timing['simulation'])
        cur = db.execute('INSERT INTO simulations(team_id,started_at,deadline,personal_minutes,team_minutes) VALUES(?,?,?,?,?)', (t['id'], start,cap or 0,timing['personal'],timing['team']))
        sid = cur.lastrowid
        for i, member in enumerate(members):
            make_attempt('sim_personal', papers[i], uid=member['user_id'], team_id=t['id'], sim_id=sid,
                         start=start, deadline=deadline_for(start,timing['personal'],cap),rules=rules['personal'],minutes=timing['personal'])
        team_aid = make_attempt('sim_team', papers[len(members)], team_id=t['id'], sim_id=sid,rules=rules['team'],minutes=timing['team'])
        db.execute('UPDATE simulations SET team_attempt_id=? WHERE id=?', (team_aid, sid))
        db.commit()
        return jsonify(simulation_id=sid)

    @app.post('/simulation/<int:sid>/team/start')
    @login_required
    def start_sim_team(sid):
        db = get_db()
        sim = db.execute('SELECT * FROM simulations WHERE id=?', (sid,)).fetchone()
        if not sim or not db.execute('SELECT 1 FROM team_members WHERE team_id=? AND user_id=?', (sim['team_id'], session['uid'])).fetchone():
            abort(403)
        for row in db.execute('SELECT * FROM attempts WHERE simulation_id=? AND kind="sim_personal"', (sid,)).fetchall():
            expire(row)
        db.execute('BEGIN IMMEDIATE')
        team = db.execute('SELECT * FROM attempts WHERE id=?', (sim['team_attempt_id'],)).fetchone()
        if team['started_at'] is not None:
            db.commit()
            return jsonify(attempt_id=team['id'])
        if simulation_expired(sim):
            unstarted_team_expired(sim)
            limit = (sim['deadline']-sim['started_at'])/60
            return response_error(f'完整模拟已到 {limit} 分钟截止时间；团队卷按本卷未答规则计分')
        personal = db.execute('SELECT * FROM attempts WHERE simulation_id=? AND kind="sim_personal"', (sid,)).fetchall()
        if any(x['submitted_at'] is None for x in personal):
            db.commit()
            return response_error('请等待本场所有队员完成个人对抗')
        start = now()
        db.execute('UPDATE attempts SET started_at=?,deadline=?,question_started_at=? WHERE id=?',
                   (start,deadline_for(start,team_minutes_for(sim),sim['deadline']), start, team['id']))
        db.commit()
        return jsonify(attempt_id=team['id'])

    @app.get('/api/current')
    @login_required
    def current():
        db = get_db()
        rows = db.execute('SELECT * FROM attempts WHERE user_id=? AND started_at IS NOT NULL ORDER BY id DESC LIMIT 10', (session['uid'],)).fetchall()
        t = team_for(session['uid'])
        if t:
            rows += db.execute('SELECT * FROM attempts WHERE team_id=? AND user_id IS NULL AND started_at IS NOT NULL ORDER BY id DESC LIMIT 10', (t['id'],)).fetchall()
        for row in rows:
            expire(row)
        live = [db.execute('SELECT * FROM attempts WHERE id=?', (r['id'],)).fetchone() for r in rows]
        live = [r for r in live if r['submitted_at'] is None]
        live.sort(key=lambda r: r['id'], reverse=True)
        return jsonify(attempt=attempt_payload(live[0]) if live else None)

    @app.get('/exam/<int:aid>')
    @login_required
    def exam_page(aid):
        get_attempt(aid)
        return render_template('exam.html', aid=aid)

    @app.get('/api/attempt/<int:aid>')
    @login_required
    def attempt_api(aid):
        return jsonify(attempt_payload(get_attempt(aid)))

    @app.post('/api/attempt/<int:aid>/answer')
    @login_required
    def save_answer(aid):
        row = get_attempt(aid)
        if row['submitted_at'] is not None:
            return response_error('已交卷或考试时间已到', 409)
        payload = request.get_json(silent=True) or {}
        index = payload.get('index')
        chosen = payload.get('answer')
        questions = questions_for(aid)
        if not isinstance(index, int) or index < 0 or index >= len(questions) or not isinstance(chosen, list):
            return response_error('答案格式错误')
        if index != row['current_position']:
            return response_error('此题已锁定，不能返回修改', 409)
        q = questions[index]
        keys = {x['key'] for x in json.loads(q['options'])}
        if any(not isinstance(x, str) for x in chosen) or len(set(chosen)) != len(chosen) or any(x not in keys for x in chosen) or (q['type'] != 'multi' and len(chosen) > 1):
            return response_error('答案选项无效')
        answers = json.loads(row['answers'])
        answers[str(index)] = chosen
        changed = get_db().execute('UPDATE attempts SET answers=? WHERE id=? AND submitted_at IS NULL AND current_position=?',
                                   (json.dumps(answers), aid, index)).rowcount
        get_db().commit()
        if not changed:
            return response_error('此题已锁定，不能返回修改', 409)
        return jsonify(saved=True)

    @app.post('/api/attempt/<int:aid>/advance')
    @login_required
    def advance(aid):
        row = get_attempt(aid)
        if row['submitted_at'] is not None:
            return response_error('已交卷或考试时间已到', 409)
        payload = request.get_json(silent=True) or {}
        index, skip = payload.get('index'), payload.get('skip')
        if type(index) is not int or type(skip) is not bool:
            return response_error('操作格式错误')
        db = get_db()
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM attempts WHERE id=?', (aid,)).fetchone()
        if row['submitted_at'] is not None or (row['deadline'] is not None and now() >= row['deadline']):
            db.rollback()
            expire(row)
            return response_error('已交卷或考试时间已到', 409)
        if index != row['current_position']:
            db.rollback()
            return response_error('此题已锁定，不能返回', 409)
        questions = questions_for(aid)
        answers = json.loads(row['answers'])
        if skip:
            answers[str(index)] = []
        elif not answers.get(str(index)):
            db.rollback()
            return response_error('请先作答，或确认跳过此题')
        entered = row['question_started_at']
        changed_at = min(now(), row['deadline']) if row['deadline'] is not None else now()
        if entered is not None:
            db.execute('''UPDATE attempt_questions SET duration_seconds=?
                          WHERE attempt_id=? AND position=? AND duration_seconds IS NULL''',
                       (max(0, changed_at - entered), aid, index))
        db.execute('UPDATE attempts SET answers=?,current_position=?,question_started_at=? WHERE id=?',
                   (json.dumps(answers), index + 1, changed_at, aid))
        db.commit()
        if index + 1 == len(questions):
            finalize(db.execute('SELECT * FROM attempts WHERE id=?', (aid,)).fetchone())
        return jsonify(attempt=attempt_payload(get_attempt(aid)))

    @app.post('/api/attempt/<int:aid>/submit')
    @login_required
    def submit(aid):
        row = get_attempt(aid)
        finalize(row)
        return jsonify(attempt=attempt_payload(get_attempt(aid)))

    @app.get('/api/simulation/<int:sid>')
    @login_required
    def simulation_api(sid):
        db = get_db()
        sim = db.execute('SELECT * FROM simulations WHERE id=?', (sid,)).fetchone()
        if not sim or not db.execute('SELECT 1 FROM team_members WHERE team_id=? AND user_id=?', (sim['team_id'], session['uid'])).fetchone():
            abort(403)
        if simulation_expired(sim):
            unstarted_team_expired(sim)
        rows = db.execute('SELECT a.*,u.username FROM attempts a LEFT JOIN users u ON a.user_id=u.id WHERE a.simulation_id=?', (sid,)).fetchall()
        for row in rows:
            expire(row)
        rows = db.execute('SELECT a.*,u.username FROM attempts a LEFT JOIN users u ON a.user_id=u.id WHERE a.simulation_id=?', (sid,)).fetchall()
        personals = []
        team = None
        for row in rows:
            item = {'username': row['username'], 'submitted': row['submitted_at'] is not None,
                    'score': row['score'] if row['submitted_at'] is not None else None,'max_score':maximum(row),
                    'duration_seconds': row['submitted_at'] - row['started_at'] if row['submitted_at'] else None}
            if row['kind'] == 'sim_personal':
                personals.append(item)
            else:
                team = dict(item, attempt_id=row['id'], started=row['started_at'] is not None)
        complete = bool(team and team['submitted'] and all(x['submitted'] for x in personals))
        team_max=team['max_score']
        return jsonify(id=sid, personal=personals, team=team, complete=complete,
                       score=total([x['score'] for x in personals]+[team['score']]) if complete else None,
                       max_score=total([x['max_score'] for x in personals]+[team_max]),
                       team_max_score=team_max,
                       team_limit_minutes=team_minutes_for(sim),
                       duration_seconds=sum(x['duration_seconds'] for x in personals) + team['duration_seconds'] if complete else None,
                       remaining_seconds=max(0, sim['deadline'] - now()) if sim['deadline'] else None)

    @app.get('/simulation/<int:sid>')
    @login_required
    def simulation_page(sid):
        sim = get_db().execute('SELECT * FROM simulations WHERE id=?', (sid,)).fetchone()
        if not sim or not get_db().execute('SELECT 1 FROM team_members WHERE team_id=? AND user_id=?', (sim['team_id'], session['uid'])).fetchone():
            abort(403)
        return render_template('simulation.html', sid=sid)

    def import_page(**context):
        records = []
        for conflict in get_db().execute('SELECT payload,reason FROM question_import_conflicts ORDER BY rowid DESC LIMIT 100'):
            row = json.loads(conflict['payload'])
            choices = {option['key']:option['text'] for option in row['options']}
            records.append({'stem':row['stem'], 'source':row.get('source',''),
                            'answer_texts':[choices[key] for key in row['answer']], 'reason':conflict['reason']})
        pending = get_db().execute('SELECT COUNT(*) FROM question_import_conflicts').fetchone()[0]
        return render_template('admin.html', count=question_count(), pending_conflicts=pending,
                               conflict_records=records, **context)

    @app.route('/admin/import', methods=['GET', 'POST'])
    @admin_required
    def admin_import():
        if request.method == 'GET':
            return import_page()
        upload = request.files.get('file')
        if not upload or not upload.filename:
            return response_error('请选择文件')
        try:
            rows = parse_file(upload.filename, upload.read())
            default_source = (request.form.get('source') or '管理员导入（未核验）').strip()[:150]
            counts, preview = inspect_rows(get_db(), rows, default_source)
            token = secrets.token_urlsafe(24)
            path = ROOT / 'data' / f'import_{token}.json'
            path.write_text(json.dumps({'rows': rows, 'source': default_source}, ensure_ascii=False), encoding='utf-8')
            session['import_token'] = token
            return import_page(counts=counts, preview=preview, token=token)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return response_error(str(exc))

    @app.post('/admin/import/commit')
    @admin_required
    def admin_import_commit():
        token = request.form.get('token')
        if not token or token != session.get('import_token'):
            abort(403)
        path = ROOT / 'data' / f'import_{token}.json'
        if not path.exists():
            return response_error('预览已失效')
        payload = json.loads(path.read_text(encoding='utf-8'))
        counts = import_rows(get_db(), payload['rows'], payload['source'])
        path.unlink()
        session.pop('import_token', None)
        return import_page(committed=counts)

    @app.errorhandler(403)
    def forbidden(exc):
        return (jsonify(error='无权访问') if request.path.startswith('/api/') else '无权访问'), 403

    register_favorites(app, get_db, login_required)
    register_question_bank(app, get_db, login_required)
    register_drill(app, get_db, login_required)
    return app


if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=5000, threaded=True, debug=False)
