"""Non-destructive question aliases and reviewed preset distillation.

Legacy question IDs and fingerprints remain untouched. Only the effective bank
uses aliases; historical attempts keep their original options and answer keys.
"""
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import unicodedata


QUOTES = str.maketrans({'“':'"', '”':'"', '‘':"'", '’':"'"})


def display_text(value):
    """Match legacy clean semantics; the UI renders all question text literally."""
    text = unicodedata.normalize('NFKC', str(value))
    return re.sub(r'\s+', ' ', text).strip().casefold()


def stem_text(value):
    # Even Chinese spaces, question marks and empty brackets can be a query.
    # More aggressive PDF/OCR equivalence belongs only to the reviewed manifest.
    return display_text(value)


def reviewed_text(value):
    """Only used for immutable, individually audited preset fingerprints."""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value))).translate(QUOTES).casefold()


@lru_cache(maxsize=1)
def reviewed_members():
    data = json.loads((Path(__file__).parent/'data/reviewed_duplicate_groups.json').read_text(encoding='utf-8'))
    return {member['fingerprint']: group for group in data['groups'] for member in group['members']}


def decode_question(row):
    item = dict(row)
    for field in ('options', 'answer'):
        if isinstance(item[field], str):
            item[field] = json.loads(item[field])
    return item


def answer_texts(row, normalizer=display_text):
    choices = {option['key']: normalizer(option['text']) for option in row['options']}
    return tuple(sorted(choices[key] for key in row['answer']))


def comparison_keys(row, mark):
    options = tuple(sorted(display_text(option['text']) for option in row['options']))
    # A normalization collision must not turn two different options into one.
    keys = [('legacy', mark)]
    if len(set(options)) == len(options):
        keys.append(('display', row['type'], stem_text(row['stem']), options))
    group = reviewed_members().get(mark)
    if (group and row['type'] == group['type']
        and sorted(reviewed_text(option['text']) for option in row['options']) == group['options']
        and list(answer_texts(row, reviewed_text)) == group['answers']):
        keys.append(('reviewed', group['id']))
    return keys


def signature(row, key):
    return answer_texts(row, reviewed_text if key[0]=='reviewed' else display_text)


class QuestionMatcher:
    def __init__(self, db):
        self.buckets = defaultdict(list)
        for row in db.execute('SELECT * FROM questions ORDER BY id'):
            decoded = decode_question(row)
            self.add(decoded, decoded['fingerprint'])

    def add(self, row, mark):
        for key in comparison_keys(row, mark):
            self.buckets[key].append(row)

    def inspect(self, row, mark):
        duplicate = False
        for key in comparison_keys(row, mark):
            candidates = self.buckets.get(key, [])
            if any(signature(other, key) != signature(row, key) for other in candidates):
                return 'conflict'
            duplicate = duplicate or bool(candidates)
        return 'duplicate' if duplicate else 'added'


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS question_duplicates(
      alias_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
      canonical_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
      CHECK(alias_id<>canonical_id))''')
    db.execute('CREATE INDEX IF NOT EXISTS question_canonical ON question_duplicates(canonical_id)')
    db.execute('''CREATE TABLE IF NOT EXISTS question_import_conflicts(
      conflict_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
      payload TEXT NOT NULL, reason TEXT NOT NULL)''')
    db.execute('''CREATE VIEW IF NOT EXISTS active_questions AS SELECT q.* FROM questions q
      WHERE NOT EXISTS(SELECT 1 FROM question_duplicates d WHERE d.alias_id=q.id)''')


def begin_write(db):
    """Serialize the whole read/decide/write cycle, including duplicate-only imports."""
    if not db.in_transaction:
        db.execute('BEGIN IMMEDIATE')


def save_conflict(db, row, mark, reason):
    encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
    conflict_key = hashlib.sha256(json.dumps([mark, answer_texts(row)], ensure_ascii=False).encode()).hexdigest()
    db.execute('INSERT OR IGNORE INTO question_import_conflicts VALUES(?,?,?,?)',
               (conflict_key, mark, encoded, reason))


def refresh_duplicates(db):
    """Rebuild aliases, choosing the oldest stored ID in each verified group."""
    begin_write(db)
    ensure_schema(db)
    rows = [decode_question(row) for row in db.execute('SELECT * FROM questions ORDER BY id')]
    parent = {row['id']: row['id'] for row in rows}
    buckets = defaultdict(list)

    def find(qid):
        while parent[qid] != qid:
            parent[qid] = parent[parent[qid]]
            qid = parent[qid]
        return qid

    for row in rows:
        for key in comparison_keys(row, row['fingerprint']):
            buckets[key].append(row)
    for key, group in buckets.items():
        if len(group) < 2:
            continue
        if len({signature(row, key) for row in group}) != 1:
            for row in group:
                save_conflict(db, row, row['fingerprint'], '已有题目题干与选项相同但答案冲突，原题保留待核验')
            continue
        for row in group[1:]:
            left, right = find(group[0]['id']), find(row['id'])
            parent[max(left, right)] = min(left, right)
    aliases = [(row['id'], find(row['id'])) for row in rows if row['id'] != find(row['id'])]
    db.execute('DELETE FROM question_duplicates')
    db.executemany('INSERT INTO question_duplicates(alias_id,canonical_id) VALUES(?,?)', aliases)
    reconcile_live_rounds(db)


def canonical_id(db, qid):
    row = db.execute('SELECT canonical_id FROM question_duplicates WHERE alias_id=?', (qid,)).fetchone()
    return row[0] if row else qid


def group_ids(db, qid):
    root = canonical_id(db, qid)
    return [root]+[row[0] for row in db.execute('SELECT alias_id FROM question_duplicates WHERE canonical_id=?', (root,))]


def reconcile_live_rounds(db):
    """Only drop blank future duplicates; preserve IDs, feedback and drafts."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='drill_items'").fetchone():
        return
    aliases = dict(db.execute('SELECT alias_id,canonical_id FROM question_duplicates'))
    for round_row in db.execute('SELECT * FROM drill_rounds WHERE finished_at IS NULL').fetchall():
        rid, position = round_row['id'], round_row['current_position']
        items = db.execute('SELECT * FROM drill_items WHERE round_id=? ORDER BY position', (rid,)).fetchall()
        protected = {item['position'] for item in items if item['position'] <= position
                     or item['answered_at'] is not None or json.loads(item['draft_answer'])}
        seen = {aliases.get(item['question_id'], item['question_id']) for item in items if item['position'] in protected}
        removed = []
        for item in items:
            if item['position'] in protected:
                continue
            root = aliases.get(item['question_id'], item['question_id'])
            if root in seen:
                removed.append(item['position'])
            else:
                seen.add(root)
        if not removed:
            continue
        db.executemany('DELETE FROM drill_items WHERE round_id=? AND position=?', [(rid, pos) for pos in removed])
        kept = [item for item in items if item['position'] not in removed]
        # Negative staging avoids PRIMARY KEY collisions while compacting positions.
        for item in kept:
            db.execute('UPDATE drill_items SET position=? WHERE round_id=? AND position=?',
                       (-item['position']-1, rid, item['position']))
        for index, item in enumerate(kept):
            db.execute('UPDATE drill_items SET position=? WHERE round_id=? AND position=?',
                       (index, rid, -item['position']-1))
        new_position = next((index for index, item in enumerate(kept) if item['position']==position), position)
        db.execute('UPDATE drill_rounds SET current_position=? WHERE id=?', (new_position, rid))
        if kept and all(item['answered_at'] is not None for item in kept):
            # Keep the last submitted item's feedback visible when pruning ends a round.
            db.execute('UPDATE drill_rounds SET finished_at=? WHERE id=?',
                       (max(item['answered_at'] for item in kept), rid))
