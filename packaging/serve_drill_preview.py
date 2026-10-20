"""Serve a disposable database for local headless browser verification."""
import argparse
import json
from pathlib import Path
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--port',required=True,type=int)
parser.add_argument('--directory',required=True,type=Path)
parser.add_argument('--module',type=Path,default=Path(__file__).resolve().parents[1]/'02_淘汰赛模考')
args=parser.parse_args()
args.directory.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(args.module.resolve()))
from app import create_app,get_db
app=create_app({'TESTING':True,'DATABASE':str((args.directory/'preview.db').resolve()),'SECRET_KEY':'drill-preview-only','SEED':True})
with app.app_context():
    answers={str(row['id']):json.loads(row['answer']) for row in get_db().execute('SELECT id,answer FROM questions')}
(args.directory/'controlled-answers.json').write_text(json.dumps(answers),encoding='utf-8')
app.run(host='127.0.0.1',port=args.port,threaded=True,debug=False,use_reloader=False)
