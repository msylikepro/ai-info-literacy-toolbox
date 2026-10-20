"""Incrementally add release questions without renumbering existing questions."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed',action='append',default=[])
    parser.add_argument('--verify',action='store_true')
    args = parser.parse_args()
    if not args.verify and not (ROOT/'data/platform.db').exists():
        print(json.dumps({'deferredUntilFirstStart':True})); return
    from app import create_app,get_db
    from importer import parse_file,import_rows
    app = create_app()
    results = {}
    labels = {'source_questions.json':'公开仓库 89757-creater/ai-info-literacy-quiz（未独立核验）',
              'source_bank.json':'公开仓库 Ziv-ZHI/ai-infolit-competition（未独立核验）'}
    with app.app_context():
        for name in args.seed:
            if name not in labels: raise ValueError('Unexpected seed filename')
            results[name] = import_rows(get_db(),parse_file(name,(ROOT/'data'/name).read_bytes()),labels[name])
        if args.verify:
            import ssl
            assert app.test_client().get('/login').status_code == 200
            results['verification'] = {'questionCount':get_db().execute('SELECT COUNT(*) FROM questions').fetchone()[0],
                                       'ssl':ssl.OPENSSL_VERSION,'passed':True}
    print(json.dumps(results,ensure_ascii=True))


if __name__ == '__main__': main()
