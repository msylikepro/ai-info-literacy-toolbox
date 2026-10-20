"""Read-only browsing of all imported questions, with independent answer reveal."""
import json

from flask import Blueprint, abort, jsonify, render_template, request


def register_question_bank(app, get_db, login_required):
    bp = Blueprint('question_bank', __name__)

    @bp.get('/question-bank')
    @login_required
    def page():
        return render_template('question_bank.html')

    @bp.get('/api/question-bank')
    @login_required
    def listing():
        query = request.args.get('q', '').strip()
        if len(query) > 200:
            return jsonify(error='关键词请控制在 200 字以内'), 400
        try:
            page_number = int(request.args.get('page', '1'))
            if not 1 <= page_number <= 1000000:
                raise ValueError()
        except ValueError:
            return jsonify(error='页码无效'), 400
        keywords = query.casefold().split()
        items = []
        # Search decoded option text, never JSON keys, answer keys or explanations.
        # Literal matching also handles %, _, backslashes and Chinese uniformly.
        for row in get_db().execute('SELECT id,type,stem,options,module FROM active_questions ORDER BY id'):
            options = json.loads(row['options'])
            content = (row['stem'] + ' ' + ' '.join(option['text'] for option in options)).casefold()
            if all(word in content for word in keywords):
                items.append({**dict(row), 'options': options})
        total = len(items)
        page_size = 20
        pages = max(1, (total + page_size - 1) // page_size)
        page_number = min(page_number, pages)
        offset = (page_number - 1) * page_size
        return jsonify(items=items[offset:offset + page_size], total=total, page=page_number,
                       pages=pages, page_size=page_size, query=query)

    @bp.get('/api/question-bank/<int:qid>/answer')
    @login_required
    def answer(qid):
        row = get_db().execute('SELECT id,answer,explanation,source FROM questions WHERE id=?', (qid,)).fetchone()
        if row is None:
            abort(404)
        return jsonify(id=qid, correct=json.loads(row['answer']), explanation=row['explanation'], source=row['source'])

    app.register_blueprint(bp)
