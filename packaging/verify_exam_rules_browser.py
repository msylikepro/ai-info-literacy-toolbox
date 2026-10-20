"""Verify configurable exam rules against a fresh, isolated local fixture."""
import argparse
from pathlib import Path
import subprocess
import sys
import threading

parser = argparse.ArgumentParser()
parser.add_argument('--module', required=True, type=Path)
parser.add_argument('--directory', required=True, type=Path)
args = parser.parse_args()
args.directory.mkdir(parents=True, exist_ok=True)
db = args.directory.resolve() / 'browser-fixture.db'
if db.exists():
    raise SystemExit('Use a new verification directory')
sys.path.insert(0, str(args.module.resolve()))
from app import create_app, get_db
from importer import import_rows
from werkzeug.serving import make_server, WSGIRequestHandler

app = create_app({'TESTING': True, 'DATABASE': str(db), 'SECRET_KEY': 'isolated-exam-rules-fixture', 'SEED': False})
with app.app_context():
    imported = import_rows(get_db(), [
        {'type': kind, 'stem': f'规则验收 {kind} 第{i}题', 'options': ['正确', '错误'] if kind == 'judge' else ['选项甲', '选项乙', '选项丙'],
         'answer': 'AB' if kind == 'multi' else ('正确' if kind == 'judge' else 'A'),
         'explanation': '仅用于隔离浏览器验证。'}
        for kind in ('single', 'multi', 'judge') for i in range(18)
    ])
    assert imported['added'] == 54, imported

class Quiet(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass

server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
node = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
try:
    subprocess.run([str(node), str(Path(__file__).resolve().parent / 'tests/exam_rules_browser.cjs'),
                    'http://127.0.0.1:' + str(server.server_port), str(args.directory.resolve())],
                   check=True, timeout=180)
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)
