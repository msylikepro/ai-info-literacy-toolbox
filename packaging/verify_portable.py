"""Exercise a freshly extracted ZIP with no system Python/Node on PATH."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.parse
import zipfile


def run(command, env, cwd, timeout=90):
    result = subprocess.run([str(x) for x in command], env=env, cwd=cwd, capture_output=True,
                            encoding='utf-8', errors='replace', timeout=timeout)
    if result.returncode:
        raise AssertionError(f'Command failed ({result.returncode}): {command}\n{result.stdout}\n{result.stderr}')
    return result.stdout.strip()


def verify(archive, destination):
    from build_portable import EXE_NAME
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Use an empty verification directory to avoid touching existing user data')
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for name in package.namelist():
            lower = name.lower()
            assert not any(x in lower for x in ('api-keys.dpapi', 'platform.db', 'admin_credentials', '.secret_key', 'manual-audits', '__pycache__')), name
        package.extractall(destination)
    root = destination / archive.stem
    manifest = json.loads((root / 'build-manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        file = root / item['path']
        with file.open('rb') as source:
            assert hashlib.file_digest(source, 'sha256').hexdigest() == item['sha256'], str(file)
    env = dict(os.environ)
    env['PATH'] = os.pathsep.join([os.path.join(env['SYSTEMROOT'], 'System32'),
        os.path.join(env['SYSTEMROOT'], 'System32', 'WindowsPowerShell', 'v1.0')])
    # These intentionally wrong settings reproduce another computer's unrelated installations.
    env.update(PYTHONHOME='Z:\\not-installed', PYTHONPATH='Z:\\not-installed', PYTHONUTF8='1',
               PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', NODE_OPTIONS='--invalid-from-other-project')
    for name in list(env):
        if name.startswith(('OPENAI_', 'QWEN_', 'DASHSCOPE_', 'DEEPSEEK_', 'CODEX_PROXY', 'CHECKER_')) or name == 'ADMIN_PASSWORD':
            env.pop(name, None)
    report = destination / '启动自检.json'
    run([root / EXE_NAME, '--check', report], env, destination)
    check = json.loads(report.read_text(encoding='utf-8'))
    assert check['passed'], check
    for key in ('examUrl', 'checkerUrl'):
        endpoint = urllib.parse.urlsplit(check[key])
        with socket.socket() as connection:
            connection.settimeout(0.5)
            assert connection.connect_ex(('127.0.0.1', endpoint.port)) != 0, 'Launcher exit left a server running'
    db = root / '02_淘汰赛模考/data/platform.db'
    with sqlite3.connect(db) as connection:
        assert connection.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 1
        assert connection.execute('SELECT username FROM users').fetchone()[0] == 'admin'
        count = connection.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
        assert count >= 40
        effective_count = count
        if tuple(map(int, manifest['version'].split('.'))) >= (1, 10, 0):
            assert count == 373
            effective_count = connection.execute('SELECT COUNT(*) FROM active_questions').fetchone()[0]
            assert effective_count == 229
            assert connection.execute('SELECT COUNT(*) FROM question_duplicates').fetchone()[0] == 144
        assert connection.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 0
    python = root / 'runtime/python/python.exe'
    exam_code = r'''
import json, sys
from pathlib import Path
root = Path(sys.argv[1]); sys.path.insert(0, str(root / '02_淘汰赛模考'))
from app import create_app, get_db
app = create_app()
client = app.test_client()
response = client.post('/register', data={'username':'便携版验证队员','password':'portable-test-password'})
assert response.status_code == 302
aid = client.post('/training/personal/start').json['attempt_id']
state = client.get(f'/api/attempt/{aid}').json
assert state['question_count'] == 10
assert state['remaining_seconds'] is None
for index in range(10):
    with app.app_context():
        correct = get_db().execute('SELECT q.answer FROM questions q JOIN attempt_questions a ON a.question_id=q.id WHERE a.attempt_id=? AND a.position=?', (aid,index)).fetchone()[0]
    answer = client.post(f'/api/attempt/{aid}/answer', json={'index':index,'answer':json.loads(correct)})
    assert answer.status_code == 200, answer.data
    advance = client.post(f'/api/attempt/{aid}/advance', json={'index':index,'skip':False})
    assert advance.status_code == 200, advance.data
client.post(f'/api/attempt/{aid}/submit')
result = client.get(f'/api/attempt/{aid}').json
assert result['score'] == 20, result
assert len(result['questions']) == 10
assert result['submitted_at'] is not None
print(json.dumps({'question_count':10,'score':result['score'],'saved':True}))
'''
    exam = json.loads(run([python, '-c', exam_code, root], env, destination))
    with sqlite3.connect(db) as connection:
        assert connection.execute('SELECT score FROM attempts').fetchone()[0] == 20

    class ApiStub(BaseHTTPRequestHandler):
        calls = []

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.calls.append((self.path, body['model']))
            text = json.dumps({'answer': 'A', 'reason': '本地受控响应，仅验证便携版调用链'}, ensure_ascii=False)
            data = {'status': 'completed', 'output': [{'type':'message', 'content':[{'type':'output_text','text':text}]}]} if self.path.endswith('/responses') else {'choices':[{'message':{'content':text},'finish_reason':'stop'}]}
            payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), ApiStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ai_env = dict(env)
    for prefix in ('OPENAI', 'QWEN', 'DEEPSEEK'):
        ai_env[prefix + '_API_KEY'] = 'local-verification-key'
        ai_env[prefix + '_BASE_URL'] = f'http://127.0.0.1:{server.server_port}/v1'
    ai_env['NO_PROXY'] = '127.0.0.1,localhost'
    try:
        powershell = Path(env['SYSTEMROOT']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        question = destination / '中文题目.txt'
        question.write_text('单选题：便携版验证。A. 正确 B. 错误', encoding='utf-8')
        output = run([powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                      root / '01_三AI同查/run_solver.ps1', '-File', question, '-Json', '-Timeout', '10'], ai_env, destination)
        ai = json.loads(output.lstrip('\ufeff'))
        assert len(ai['models']) == 3
        assert all(m['answer'] == 'A' and not m['error'] for m in ai['models']), ai
        assert len(ApiStub.calls) == 3
    finally:
        server.shutdown(); server.server_close()
    # Resolve local PDF links exactly as a browser would, including Chinese names.
    from html.parser import HTMLParser
    class Links(HTMLParser):
        def __init__(self): super().__init__(); self.hrefs = []
        def handle_starttag(self, tag, attrs):
            if tag == 'a':
                self.hrefs += [v for k,v in attrs if k == 'href']
    pdf_dir = root / '03_50知识点检验/03_PDF参考资料'
    links = Links(); links.feed((pdf_dir / '_资料索引.html').read_text(encoding='utf-8'))
    pdf_links = [x for x in links.hrefs if not urllib.parse.urlsplit(x).scheme and x.lower().endswith('.pdf')]
    assert len(pdf_links) == 11
    for name in pdf_links:
        assert (pdf_dir / urllib.parse.unquote(name)).read_bytes().startswith(b'%PDF'), name
    summary = {'passed':True,'relocatedPath':str(root),'systemPythonAndNodeOnPath':False,
               'manifestFilesVerified':len(manifest['files']),'questionBankCount':count,'effectiveQuestionCount':effective_count,
               'examPractice':exam,'aiLocalStubCalls':len(ApiStub.calls),'pdfLinksVerified':len(pdf_links),
               'servicesStoppedOnExit':True,'startupCheck':check}
    (destination / '便携版验证结果.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    verify(args.archive.resolve(), args.destination.resolve())
