"""Per-account saved questions with independent, unscored review."""
import json
import time

from flask import Blueprint, abort, jsonify, render_template, request, session
from distillation import group_ids


def register_favorites(app, get_db, login_required):
    with app.app_context():
        get_db().executescript('''
          CREATE TABLE IF NOT EXISTS favorite_questions(
            user_id INTEGER NOT NULL REFERENCES users(id),
            question_id INTEGER NOT NULL REFERENCES questions(id),
            saved_at INTEGER NOT NULL, PRIMARY KEY(user_id,question_id));
          CREATE INDEX IF NOT EXISTS favorites_user_order
            ON favorite_questions(user_id,saved_at DESC,question_id DESC);
        ''')
        get_db().commit()
    bp = Blueprint('favorites', __name__)

    def total():
        return get_db().execute('SELECT COUNT(*) FROM favorite_questions WHERE user_id=?', (session['uid'],)).fetchone()[0]

    def question(qid):
        row = get_db().execute('''SELECT q.* FROM questions q JOIN favorite_questions f ON f.question_id=q.id
          WHERE f.user_id=? AND q.id=?''', (session['uid'], qid)).fetchone()
        if row is None:
            abort(404)
        return row

    def answer_payload(row):
        return {'id': row['id'], 'correct': json.loads(row['answer']),
                'explanation': row['explanation'], 'source': row['source']}

    @bp.get('/favorites')
    @login_required
    def page():
        return render_template('favorites.html')

    @bp.get('/api/favorites')
    @login_required
    def listing():
        rows = get_db().execute('''SELECT q.id,q.type,q.stem,q.module,f.saved_at FROM favorite_questions f
          JOIN questions q ON q.id=f.question_id WHERE f.user_id=?
          ORDER BY f.saved_at DESC,f.question_id DESC''', (session['uid'],)).fetchall()
        return jsonify(total=len(rows), items=[dict(row) for row in rows])

    @bp.post('/api/favorites/<int:qid>')
    @login_required
    def add(qid):
        db = get_db()
        if db.execute('SELECT id FROM questions WHERE id=?', (qid,)).fetchone() is None:
            abort(404)
        with db:
            family = group_ids(db, qid)
            placeholders = ','.join('?' for _ in family)
            if not db.execute('SELECT 1 FROM favorite_questions WHERE user_id=? AND question_id IN ('+placeholders+')',
                              (session['uid'],*family)).fetchone():
                db.execute('INSERT OR IGNORE INTO favorite_questions(user_id,question_id,saved_at) VALUES(?,?,?)',
                           (session['uid'], qid, int(time.time())))
        return jsonify(id=qid, favorited=True, total=total())

    @bp.delete('/api/favorites/<int:qid>')
    @login_required
    def remove(qid):
        db = get_db()
        with db:
            family = group_ids(db, qid)
            placeholders = ','.join('?' for _ in family)
            db.execute('DELETE FROM favorite_questions WHERE user_id=? AND question_id IN ('+placeholders+')',
                       (session['uid'],*family))
        return jsonify(id=qid, favorited=False, total=total())

    @bp.get('/api/favorites/<int:qid>')
    @login_required
    def detail(qid):
        row = question(qid)
        return jsonify(id=qid, type=row['type'], stem=row['stem'], options=json.loads(row['options']), module=row['module'])

    @bp.post('/api/favorites/<int:qid>/reveal')
    @login_required
    def reveal(qid):
        return jsonify(answer_payload(question(qid)))

    @bp.post('/api/favorites/<int:qid>/answer')
    @login_required
    def check(qid):
        row = question(qid)
        data = request.get_json(silent=True)
        chosen = data.get('answer') if isinstance(data, dict) else None
        keys = {option['key'] for option in json.loads(row['options'])}
        if (not isinstance(chosen, list) or not chosen
            or any(not isinstance(value, str) or value not in keys for value in chosen)
            or len(set(chosen)) != len(chosen) or row['type'] != 'multi' and len(chosen) != 1):
            return jsonify(error='请先选择有效答案'), 400
        # Favorites are review only: never write attempts, drill items or wrong history.
        return jsonify(**answer_payload(row), selected=sorted(chosen),
                       is_correct=set(chosen) == set(json.loads(row['answer'])))

    app.register_blueprint(bp)
