"""Exercise a complete real-bank round using a disposable verification database."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--module', required=True, type=Path)
parser.add_argument('--directory', required=True, type=Path)
args = parser.parse_args()
args.directory.mkdir(parents=True, exist_ok=True)
database = args.directory.resolve() / 'full-bank.db'
if database.exists():
    raise SystemExit('Use a fresh verification directory')
sys.path.insert(0, str(args.module.resolve()))
from app import create_app, get_db

config = {'TESTING': True, 'DATABASE': str(database), 'SECRET_KEY': 'isolated-drill-verification', 'SEED': True}
app = create_app(config)
client = app.test_client()
client.post('/register', data={'username': '完整题库验证', 'password': 'isolated-test-password'})
with app.app_context():
    uid = get_db().execute('SELECT id FROM users').fetchone()[0]
    answers = {row['id']: json.loads(row['answer']) for row in get_db().execute('SELECT id,answer FROM active_questions')}
    assert get_db().execute('SELECT COUNT(*) FROM questions').fetchone()[0] == 373
    assert get_db().execute('SELECT COUNT(*) FROM question_duplicates').fetchone()[0] == 144
assert len(answers) == 229, len(answers)

def concurrent_post(route, payload):
    with app.test_client() as other:
        with other.session_transaction() as session:
            session['uid'] = uid
        response = other.post(route, json=payload)
        assert response.status_code == 200, response.data
        return response.json['round']

with ThreadPoolExecutor(max_workers=2) as pool:
    rounds = list(pool.map(lambda _: concurrent_post('/api/drill/start', {'mode': 'all'}), range(2)))
assert rounds[0]['id'] == rounds[1]['id']
round = rounds[0]
rid = round['id']
seen = []
for index in range(len(answers)):
    q = round['question']
    assert not q['submitted'] and 'correct' not in q
    assert round['current_position'] == index and q['id'] not in seen
    seen.append(q['id'])
    answer = answers[q['id']]
    if index == 0:
        outside = next((option['key'] for option in q['options'] if option['key'] not in answer), None)
        answer = [outside] if outside else answer[:1]
        assert set(answer) != set(answers[q['id']])
        with ThreadPoolExecutor(max_workers=2) as pool:
            submissions = list(pool.map(lambda _: concurrent_post(f'/api/drill/{rid}/answer', {'index': index, 'answer': answer}), range(2)))
        round = submissions[0]
        assert round['wrong_count'] == 1
    else:
        if index == 37:
            assert client.post(f'/api/drill/{rid}/draft', json={'index': index, 'answer': answer}).status_code == 200
            app = create_app(config)
            client = app.test_client()
            client.post('/login', data={'username': '完整题库验证', 'password': 'isolated-test-password'})
            restored = client.get('/api/drill/current').json['round']
            assert restored['id'] == rid and restored['current_position'] == index
            assert restored['question']['id'] == q['id'] and restored['question']['selected'] == answer
        response = client.post(f'/api/drill/{rid}/answer', json={'index': index, 'answer': answer})
        assert response.status_code == 200, response.data
        round = response.json['round']
    assert round['question']['submitted'] and 'correct' in round['question']
    if index < len(answers) - 1:
        round = client.post(f'/api/drill/{rid}/next', json={'index': index}).json['round']
assert set(seen) == set(answers) and round['finished']
assert round['answered_count'] == 229 and round['correct_count'] == 228
wrong = client.get('/api/drill/wrongs').json
assert wrong['total'] == 1 and wrong['items'][0]['wrong_count'] == 1
review = client.post('/api/drill/start', json={'mode': 'wrong'}).json['round']
assert review['total'] == 1 and review['question']['id'] == seen[0]
response = client.post(f"/api/drill/{review['id']}/answer", json={'index': 0, 'answer': answers[seen[0]]})
assert response.json['round']['finished']
history = client.get('/api/drill/wrongs?status=mastered').json
assert history['total'] == 1 and history['items'][0]['wrong_count'] == 1
new_round = client.post('/api/drill/start', json={'mode': 'all'}).json['round']
assert new_round['id'] != rid and new_round['round_number'] == 2 and new_round['total'] == 229
with app.app_context():
    ids = [row[0] for row in get_db().execute('SELECT question_id FROM drill_items WHERE round_id=? ORDER BY position', (new_round['id'],))]
assert set(ids) == set(answers) and len(ids) == len(set(ids))
report = {'passed': True, 'fullBankQuestions': 229, 'legacyRowsPreserved': 373, 'duplicateAliases': 144, 'uniqueAnsweredQuestions': len(seen),
          'restartRestoresDraftAndOrder': True, 'concurrentStartCreatesOneRound': True,
          'concurrentAnswerCountsOneWrong': True, 'masteryRetainsHistory': True, 'secondRoundCoversFullBank': True}
(args.directory / '全题库刷题验证结果.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=True))
