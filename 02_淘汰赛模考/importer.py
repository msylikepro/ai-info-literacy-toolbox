import csv
import hashlib
import io
import json
import re
import unicodedata

from distillation import QuestionMatcher, begin_write, refresh_duplicates, save_conflict


def clean(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value or '')).strip())


def normalize_row(row, default_source='用户导入（未核验）'):
    kind = clean(row.get('type') or row.get('题型')).lower()
    kind = {'multiple': 'multi', '多选': 'multi', '多选题': 'multi',
            '单选': 'single', '单选题': 'single', '判断': 'judge', '判断题': 'judge'}.get(kind, kind)
    if kind not in ('single', 'multi', 'judge'):
        raise ValueError('题型须为 single、multi 或 judge')
    stem = clean(row.get('stem') or row.get('题干'))
    raw_options = row.get('options') or row.get('选项')
    if isinstance(raw_options, str):
        try:
            raw_options = json.loads(raw_options)
        except json.JSONDecodeError:
            raw_options = [x.strip() for x in raw_options.split('|')]
    if not raw_options:
        raw_options = [row.get(k) or row.get('选项' + k) for k in 'ABCDEFGH']
        raw_options = [x for x in raw_options if x]
    if not raw_options and kind == 'judge':
        raw_options = ['正确', '错误']
    if isinstance(raw_options, dict):
        raw_options = [{'key': k, 'text': v} for k, v in raw_options.items()]
    options = []
    for i, option in enumerate(raw_options or []):
        if isinstance(option, dict):
            key = clean(option.get('key') or option.get('k') or chr(65 + i)).upper()
            value = clean(option.get('text') or option.get('v') or option.get('value'))
        else:
            key, value = chr(65 + i), clean(option)
        options.append({'key': key, 'text': value})
    if not stem or len(options) < 2 or any(not x['text'] for x in options):
        raise ValueError('缺少题干或有效选项')
    keys = [x['key'] for x in options]
    if len(set(keys)) != len(keys) or len(set(clean(x['text']).casefold() for x in options)) != len(options):
        raise ValueError('选项重复')
    raw_answer = row.get('answer') or row.get('答案')
    if kind == 'judge' and clean(raw_answer) in ('正确', '对', '是', 'TRUE', '错误', '错', '否', 'FALSE'):
        truth = clean(raw_answer) in ('正确', '对', '是', 'TRUE')
        matches = [x['key'] for x in options if clean(x['text']).upper() in
                   (('正确', '对', '是', 'TRUE') if truth else ('错误', '错', '否', 'FALSE'))]
        if matches:
            raw_answer = matches[0]
    if isinstance(raw_answer, list):
        answer = [clean(x).upper() for x in raw_answer]
    else:
        value = clean(raw_answer).upper().replace(',', '').replace('，', '').replace(' ', '')
        answer = list(value)
    if not answer or len(set(answer)) != len(answer) or any(x not in keys for x in answer):
        raise ValueError('答案不对应选项')
    if kind != 'multi' and len(answer) != 1:
        raise ValueError('单选或判断题只能有一个答案')
    module = row.get('moduleTitle') or row.get('module') or row.get('知识模块') or ''
    if isinstance(module, list):
        module = ' '.join(map(str, module))
    source = row.get('source') or row.get('来源') or default_source
    if source == default_source and row.get('src'):
        source = f"{default_source} / {row['src']}"
    return {'type': kind, 'stem': stem, 'options': options, 'answer': sorted(answer),
            'source': clean(source), 'module': clean(module),
            'original_id': clean(row.get('original_id') or row.get('id') or row.get('原始编号')),
            'explanation': clean(row.get('explanation') or row.get('expl') or row.get('解析'))}


def fingerprint(row):
    parts = [row['type'], clean(row['stem']).casefold()]
    parts.extend(sorted(clean(x['text']).casefold() for x in row['options']))
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def parse_file(name, data):
    suffix = name.rsplit('.', 1)[-1].lower()
    if suffix == 'json':
        payload = json.loads(data.decode('utf-8-sig'))
        rows = payload.get('questions', []) if isinstance(payload, dict) else payload
    elif suffix == 'csv':
        rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    elif suffix == 'xlsx':
        from openpyxl import load_workbook
        sheet = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        lines = sheet.values
        header = [clean(x) for x in next(lines)]
        rows = [dict(zip(header, line)) for line in lines]
    else:
        raise ValueError('只支持 JSON、CSV、XLSX')
    if not isinstance(rows, list):
        raise ValueError('题库顶层须为数组或 questions 数组')
    if suffix == 'json':
        expanded = []
        for row in rows:
            expanded.append(row)
            if isinstance(row, dict):
                for variant in row.get('variants') or []:
                    if isinstance(variant, dict):
                        item = dict(row, **variant)
                        item['original_id'] = f"{row.get('id', '')}-{variant.get('kind', 'variant')}"
                        expanded.append(item)
        rows = expanded
    return rows


def inspect_rows(db, rows, default_source='用户导入（未核验）', commit=False):
    counts = {'added': 0, 'duplicate': 0, 'invalid': 0}
    preview = []
    if commit:
        begin_write(db)
    matcher = QuestionMatcher(db)
    for index, raw in enumerate(rows, 1):
        try:
            row = normalize_row(raw, default_source)
            mark = fingerprint(row)
            status = matcher.inspect(row, mark)
            if status == 'conflict':
                counts['conflict'] = counts.get('conflict', 0) + 1
                if commit:
                    save_conflict(db, row, mark, '题干与选项相同但答案内容冲突，未覆盖原题')
                raise ValueError('答案内容冲突，原始导入记录将保留待核验：' + row['stem'][:70])
            matcher.add(row, mark)
            # Preserve distinct source rows as aliases, retaining the old fingerprint.
            # Repeated identical uploads still do not add physical rows.
            exists = db.execute('SELECT 1 FROM questions WHERE fingerprint=?', (mark,)).fetchone()
            if commit and not exists:
                db.execute('INSERT INTO questions(fingerprint,type,stem,options,answer,source,module,original_id,explanation) VALUES(?,?,?,?,?,?,?,?,?)',
                           (mark, row['type'], row['stem'], json.dumps(row['options'], ensure_ascii=False),
                            json.dumps(row['answer']), row['source'], row['module'], row['original_id'], row['explanation']))
            preview.append({'line': index, 'status': status, 'stem': row['stem'][:100], 'source': row['source']})
        except (ValueError, TypeError, AttributeError) as exc:
            status = 'invalid'
            preview.append({'line': index, 'status': status, 'stem': str(exc), 'source': ''})
        counts[status] += 1
    if commit:
        refresh_duplicates(db)
        db.commit()
    return counts, preview


def import_rows(db, rows, default_source='用户导入（未核验）'):
    return inspect_rows(db, rows, default_source, True)[0]
