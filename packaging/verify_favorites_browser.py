"""Serve isolated review fixtures to Edge; never start the user's real database."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading

parser = argparse.ArgumentParser()
parser.add_argument('--module', required=True, type=Path)
parser.add_argument('--directory', required=True, type=Path)
parser.add_argument('--scenario', choices=('favorites','question-bank'), default='favorites')
args = parser.parse_args()
args.directory.mkdir(parents=True, exist_ok=True)
db = args.directory.resolve() / 'browser-fixture.db'
if db.exists(): raise SystemExit('Use a new verification directory')
sys.path.insert(0, str(args.module.resolve()))
from app import create_app, get_db
from importer import import_rows
from werkzeug.serving import make_server, WSGIRequestHandler

app = create_app({'TESTING':True, 'DATABASE':str(db), 'SECRET_KEY':'local-browser-fixture', 'SEED':False})
with app.app_context():
    fixtures = [
        {'type':'single','stem':'收藏复习：单选示例','options':['选项甲','选项乙','选项丙'],'answer':'A','explanation':'仅用于本机界面验收。'},
        {'type':'multi','stem':'收藏复习：多选示例','options':['选项甲','选项乙','选项丙'],'answer':'AB','explanation':'选中甲和乙。'},
        {'type':'judge','stem':'收藏复习：判断示例','answer':'正确','explanation':'答案为正确。'}]
    if args.scenario == 'question-bank':
        fixtures = [
            {'type':'single','stem':'人工智能基础 GPT <img src=x onerror="window.bankInjected=1">','options':['机器学习 %_\\','知识表示'],'answer':'A','explanation':'本机验证 <script>window.bankInjected=1</script>'},
            {'type':'multi','stem':'人工智能应用','options':['自然语言处理','视觉识别','数据挖掘'],'answer':'AB'},
            {'type':'judge','stem':'浏览复习不改变学习记录','answer':'正确'}] + [
            {'type':'single','stem':f'分页题目 {i}','options':['选项甲','选项乙'],'answer':'A'} for i in range(22)]
    import_rows(get_db(), fixtures)
    rows = [dict(row) for row in get_db().execute('SELECT id,type,options,answer FROM questions')]
    for row in rows:
        row['options'] = json.loads(row['options']); row['answer'] = json.loads(row['answer'])
    (args.directory / 'controlled-questions.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
class Quiet(WSGIRequestHandler):
    def log_request(self, *args, **kwargs): pass
server = make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
node = Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
try:
    script = 'question_bank_browser.cjs' if args.scenario == 'question-bank' else 'favorites_browser.cjs'
    subprocess.run([str(node),str(Path(__file__).resolve().parent/'tests'/script),
                    'http://127.0.0.1:'+str(server.server_port),str(args.directory.resolve())],check=True,timeout=150)
finally:
    server.shutdown(); server.server_close(); thread.join(timeout=10)
