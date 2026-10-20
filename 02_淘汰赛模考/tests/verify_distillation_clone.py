"""Verify migration on a temporary SQLite backup; print only aggregate evidence.

This never writes the source database and never selects credential columns.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from contextlib import closing, ExitStack

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app, get_db, question_count


def digest_rows(rows):
    return hashlib.sha256(json.dumps([tuple(row) for row in rows],ensure_ascii=False).encode()).hexdigest()


def snapshot(db, template=None):
    tables = ('questions','attempts','attempt_questions','favorite_questions','wrong_questions')
    result = {}
    for name in template or tables:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone():
            continue
        columns = template[name]['columns'] if template else [row['name'] for row in db.execute('PRAGMA table_info('+name+')')]
        selected = ','.join('"'+column+'"' for column in columns)
        result[name] = {'count':db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0], 'columns':columns,
                        'sha256':digest_rows(db.execute('SELECT '+selected+' FROM '+name+' ORDER BY rowid'))}
    return result


def protected_items(db):
    result = {}
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='drill_items'").fetchone():
        return result
    for row in db.execute('''SELECT d.*,r.current_position FROM drill_items d
      JOIN drill_rounds r ON r.id=d.round_id WHERE r.finished_at IS NULL'''):
        if (row['position'] <= row['current_position'] or row['answered_at'] is not None
            or json.loads(row['draft_answer'])):
            result[(row['round_id'],row['question_id'])] = tuple(row[key] for key in
                ('draft_answer','answer','is_correct','answered_at'))
    return result


def verify():
    source = ROOT/'data/platform.db'
    source_hash_before = hashlib.sha256(source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='question-distillation-clone-') as folder, ExitStack() as connections:
        clone = Path(folder)/'legacy.db'
        # SQLite backup includes a consistent snapshot if the original is in WAL mode.
        with closing(sqlite3.connect('file:'+source.as_posix()+'?mode=ro',uri=True)) as original:
            with closing(sqlite3.connect(clone)) as target:
                original.backup(target)
        db = connections.enter_context(closing(sqlite3.connect(clone)))
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        original_snapshot = snapshot(db)
        original_protected = protected_items(db)
        db.close()
        config = {'DATABASE':str(clone), 'TESTING':True, 'SECRET_KEY':'clone-test-only', 'SEED':False}
        first_app = create_app(config)
        with first_app.app_context():
            migrated_db = get_db()
            assert snapshot(migrated_db,original_snapshot)==original_snapshot, 'Original columns changed during legacy schema migration'
            migrated_protected = protected_items(migrated_db)
            assert all(migrated_protected.get(key)==value for key,value in original_protected.items())
            assert question_count()==229
        db = connections.enter_context(closing(sqlite3.connect(clone)))
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        legacy_ids = {row['fingerprint']:row['id'] for row in db.execute('SELECT id,fingerprint FROM questions')}
        manifest = json.loads((ROOT/'data/reviewed_duplicate_groups.json').read_text(encoding='utf-8'))
        member_ids = [[legacy_ids[m['fingerprint']] for m in group['members'] if m['fingerprint'] in legacy_ids]
                      for group in manifest['groups']]
        triple = next(sorted(group) for group in member_ids if len(group)>=3)
        pair = next(sorted(group) for group in member_ids if len(group)>=2 and not set(group)&set(triple))
        # Add a known synthetic account only inside the clone. No real credential is read.
        uid = db.execute('INSERT INTO users(username,password_hash,is_admin) VALUES(?,?,0)',
                         ('clone-distillation-check','not-a-login')).lastrowid
        rid_feedback = db.execute("INSERT INTO drill_rounds(user_id,mode,round_number,started_at,current_position) VALUES(?,'all',1,1,1)",(uid,)).lastrowid
        rid_draft = db.execute("INSERT INTO drill_rounds(user_id,mode,round_number,started_at,current_position) VALUES(?,'wrong',1,1,1)",(uid,)).lastrowid
        rid_finished = db.execute("INSERT INTO drill_rounds(user_id,mode,round_number,started_at,finished_at,current_position) VALUES(?,'all',0,1,2,1)",(uid,)).lastrowid
        for rid,ids in ((rid_feedback,[triple[0],triple[1],pair[0],pair[1],triple[2]]),
                        (rid_draft,[triple[0],triple[1],pair[0],pair[1]]),
                        (rid_finished,[triple[0],triple[1]])):
            for position,qid in enumerate(ids):
                answered = position==0 or (rid in (rid_feedback,rid_finished) and position==1)
                draft = '["A"]' if answered or (rid==rid_draft and position==1) or position==4 else '[]'
                db.execute('INSERT INTO drill_items(round_id,position,question_id,draft_answer,answer,is_correct,answered_at) VALUES(?,?,?,?,?,?,?)',
                           (rid,position,qid,draft,'["A"]' if answered else None,1 if answered else None,2 if answered else None))
        db.execute('INSERT INTO favorite_questions VALUES(?,?,1)',(uid,triple[1]))
        aid = db.execute("INSERT INTO attempts(kind,user_id,started_at,submitted_at,score) VALUES('personal',?,1,2,2)",(uid,)).lastrowid
        db.execute('INSERT INTO attempt_questions(attempt_id,position,question_id) VALUES(?,0,?)',(aid,triple[1]))
        for qid in triple[:2]:
            db.execute('INSERT INTO wrong_questions(user_id,question_id,wrong_count,first_wrong_at,last_wrong_at,last_wrong_answer) VALUES(?,?,1,1,2,?)',
                       (uid,qid,'["A"]'))
        db.commit()
        before = snapshot(db)
        protected = protected_items(db)
        cursors = dict(db.execute('SELECT id,current_position FROM drill_rounds WHERE finished_at IS NULL'))
        finished = digest_rows(db.execute('SELECT * FROM drill_items WHERE round_id=? ORDER BY position',(rid_finished,)))
        pending_before = db.execute('SELECT COUNT(*) FROM drill_items WHERE answered_at IS NULL').fetchone()[0]
        db.close()
        app = create_app(config)
        with app.app_context():
            db = get_db()
            assert snapshot(db)==before, 'Historical question/exam/favorite/wrong rows changed'
            active = question_count()
            assert active==229, active
            after_protected = protected_items(db)
            assert all(after_protected.get(key)==value for key,value in protected.items()), 'Draft or answered content changed'
            assert dict(db.execute('SELECT id,current_position FROM drill_rounds WHERE finished_at IS NULL'))==cursors, 'Current cursor changed'
            assert digest_rows(db.execute('SELECT * FROM drill_items WHERE round_id=? ORDER BY position',(rid_finished,)))==finished
            assert db.execute('SELECT COUNT(*) FROM drill_items WHERE round_id=?',(rid_feedback,)).fetchone()[0]==4
            assert db.execute('SELECT COUNT(*) FROM drill_items WHERE round_id=?',(rid_draft,)).fetchone()[0]==3
            pending_after = db.execute('SELECT COUNT(*) FROM drill_items WHERE answered_at IS NULL').fetchone()[0]
            alias_count = db.execute('SELECT COUNT(*) FROM question_duplicates').fetchone()[0]
            first_migration = digest_rows(db.execute('SELECT * FROM drill_items ORDER BY round_id,position'))
            alias_digest = digest_rows(db.execute('SELECT * FROM question_duplicates ORDER BY alias_id'))
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
            assert integrity=='ok'
        again = create_app(config)
        with again.app_context():
            db=get_db()
            assert snapshot(db)==before
            assert digest_rows(db.execute('SELECT * FROM drill_items ORDER BY round_id,position'))==first_migration
            assert digest_rows(db.execute('SELECT * FROM question_duplicates ORDER BY alias_id'))==alias_digest
        source_hash_after = hashlib.sha256(source.read_bytes()).hexdigest()
        assert source_hash_before==source_hash_after, 'Source database bytes changed'
        report = {'date':'2026-10-20','source_database_unchanged':True,
                  'source_before_fixture':original_snapshot,
                  'active_questions':active,'physical_questions':before['questions']['count'],'aliases':alias_count,
                  'historical_tables_unchanged':list(before), 'protected_live_items_unchanged':len(protected),
                  'live_cursors_unchanged':len(cursors),'blank_pending_duplicates_removed':pending_before-pending_after,
                  'synthetic_current_feedback_preserved':True,'synthetic_current_draft_preserved':True,
                  'synthetic_future_draft_preserved':True,'finished_round_unchanged':True,
                  'second_start_idempotent':True,'sqlite_integrity':integrity,
                  'credential_columns_selected':False,'temporary_clone_removed_after_verification':True}
        output = ROOT/'docs/题库蒸馏克隆迁移验收_2026-10-20.json'
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':verify()
