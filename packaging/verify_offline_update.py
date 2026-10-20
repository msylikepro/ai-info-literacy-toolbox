"""Verify actual native updates on a disposable copy of the already shipped ZIP."""
import argparse
import ctypes
from contextlib import closing
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import zipfile

sys.stdout.reconfigure(encoding='utf-8')


def execute(command, env, expected=0):
    result = subprocess.run([str(x) for x in command],env=env,capture_output=True,encoding='utf-8',errors='replace',timeout=150)
    if expected == 0 and result.returncode != 0:
        raise AssertionError(f'Command failed: {command}\n{result.stdout}\n{result.stderr}')
    if expected != 0 and result.returncode == 0: raise AssertionError('Invalid update unexpectedly succeeded')
    return result


def hashes(root, names):
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}


def database_state(file):
    with closing(sqlite3.connect(file)) as db:
        db.row_factory=sqlite3.Row
        state={table:[dict(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid')]
               for table in ('users','teams','team_members','questions','simulations','attempts','attempt_questions')}
        # Normalize only newly introduced nullable snapshot columns; all old
        # fields and actual non-null rules/timing must still compare exactly.
        for row in state['attempts']:
            row.setdefault('rules_json',None);row.setdefault('time_limit_minutes',None)
        for row in state['simulations']:
            row.setdefault('personal_minutes',None);row.setdefault('team_minutes',None)
        state['exam_settings']=[dict(row) for row in db.execute('SELECT * FROM exam_settings ORDER BY user_id')] if db.execute("SELECT 1 FROM sqlite_master WHERE name='exam_settings'").fetchone() else []
        for row in state['exam_settings']:row.setdefault('timing_json',None)
        return state


def favorite_state(file):
    with closing(sqlite3.connect(file)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='favorite_questions'").fetchone():
            return None
        return db.execute('SELECT * FROM favorite_questions ORDER BY user_id,question_id').fetchall()


def verify(old_zip, update_folder, destination):
    assert update_folder.with_name(update_folder.name+'.zip').is_file(), 'Versioned update ZIP has the wrong filename'
    description=json.loads((update_folder/'升级清单.json').read_text(encoding='utf-8'))
    target_version=description['toVersion']
    if destination.exists() and any(destination.iterdir()): raise ValueError('Use an empty verification directory')
    destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(old_zip) as package: package.extractall(destination)
    root = destination/old_zip.stem
    updater = update_folder/'双击升级.exe'
    assert updater.is_file(), 'Native offline updater is not built'
    env = dict(os.environ)
    for name in list(env):
        if name.startswith(('OPENAI_','QWEN_','DASHSCOPE_','DEEPSEEK_','CODEX_PROXY','CHECKER_')) or name == 'ADMIN_PASSWORD': env.pop(name,None)
    env.update(PATH=os.pathsep.join([env['SYSTEMROOT']+'\\System32',env['SYSTEMROOT']+'\\System32\\WindowsPowerShell\\v1.0']),
               PYTHONHOME='Z:\\not-installed',PYTHONPATH='Z:\\not-installed',NODE_OPTIONS='--invalid-external-setting',
               PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
    print('Initialize shipped version and create personal data',flush=True)
    execute([root/'AI信息素养工具箱.exe','--check',destination/'old-check.json'],env)
    python = root/'runtime/python/python.exe'
    fixture_code = r'''
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'02_淘汰赛模考'))
from app import create_app,get_db
from importer import import_rows
app=create_app();client=app.test_client()
assert client.post('/register',data={'username':'升级保留用户','password':'portable-password'}).status_code==302
with app.app_context():
    import_rows(get_db(),[{'type':'single','stem':'升级前自建题，必须保留','options':['甲','乙'],'answer':'A','source':'自建题库'}])
aid=client.post('/training/personal/start').json['attempt_id']
for index in range(10):
    with app.app_context():
        answer=json.loads(get_db().execute('SELECT q.answer FROM questions q JOIN attempt_questions a ON a.question_id=q.id WHERE a.attempt_id=? AND a.position=?',(aid,index)).fetchone()[0])
    assert client.post(f'/api/attempt/{aid}/answer',json={'index':index,'answer':answer}).status_code==200
    assert client.post(f'/api/attempt/{aid}/advance',json={'index':index,'skip':False}).status_code==200
client.post(f'/api/attempt/{aid}/submit')
assert client.get(f'/api/attempt/{aid}').json['score']==20
if 'favorites' in app.blueprints:
    with app.app_context(): qid=get_db().execute('SELECT id FROM questions ORDER BY id LIMIT 1').fetchone()[0]
    assert client.post(f'/api/favorites/{qid}').status_code==200
    assert client.get('/api/favorites').json['total']==1
'''
    execute([python,'-B','-c',fixture_code,root],env)
    powershell=Path(env['SYSTEMROOT'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    credentials=root/'01_三AI同查/data/api-keys.dpapi.json'
    credentials.parent.mkdir(exist_ok=True)
    ps=destination/'make-test-key.ps1'
    ps.write_text("param([string]$OutputFile)\nAdd-Type -AssemblyName System.Security\n$b=[Text.Encoding]::UTF8.GetBytes('offline-upgrade-test-key')\n$e=[Security.Cryptography.ProtectedData]::Protect($b,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)\n@{openai_key=[Convert]::ToBase64String($e);openai_base_url='https://example.invalid/v1'} | ConvertTo-Json | Set-Content -LiteralPath $OutputFile -Encoding UTF8\n",encoding='utf-8-sig')
    execute([powershell,'-NoProfile','-ExecutionPolicy','Bypass','-File',ps,'-OutputFile',credentials],env)
    reports=root/'03_50知识点检验/02_网站检测工具/reports'
    reports.mkdir(exist_ok=True)
    resources=json.loads((root/'03_50知识点检验/02_网站检测工具/data/resources.json').read_text(encoding='utf-8'))
    (reports/'manual-audits.json').write_text(json.dumps({'version':1,'items':{str(resources[0]['id']):{'checked':True,'reviewedAt':'2026-10-15T00:00:00Z','updatedAt':'2026-10-15T00:00:00Z'}}}),encoding='utf-8')
    (reports/'latest.json').write_text(json.dumps({'job':{'status':'idle'},'results':{},'reviews':{str(resources[0]['id']):'required'}}),encoding='utf-8')
    (root/'01_三AI同查/data/thinking.json').write_text(json.dumps({'GPT':'low','Qwen':'medium','DeepSeek':'high'}),encoding='utf-8')
    personal = ['01_三AI同查/data/api-keys.dpapi.json','02_淘汰赛模考/data/admin_credentials.txt',
                '02_淘汰赛模考/data/.secret_key','03_50知识点检验/02_网站检测工具/reports/manual-audits.json',
                '03_50知识点检验/02_网站检测工具/reports/latest.json','01_三AI同查/data/thinking.json']
    saved_personal=hashes(root,personal)
    db=root/'02_淘汰赛模考/data/platform.db';saved_db=db.read_bytes();saved_state=database_state(db)
    saved_favorites=favorite_state(db)
    old_manifest=(root/'build-manifest.json').read_bytes()
    old_files=json.loads(old_manifest)['files']
    program_before=hashes(root,[row['path'] for row in old_files])
    results={}

    def apply(tag, executable=updater, expected=0):
        report=destination/(tag+'.json')
        execute([executable,'--apply','--target',root,'--report',report],env,expected)
        data=json.loads(report.read_text(encoding='utf-8'))
        assert data['passed'] == (expected==0),data
        if expected: assert (root/'build-manifest.json').read_bytes()==old_manifest
        return data

    print('Reject wrong versions, running application, and damaged package',flush=True)
    changed=json.loads(old_manifest);changed['version']='99.0.0';(root/'build-manifest.json').write_text(json.dumps(changed),encoding='utf-8')
    report=destination/'wrong-version.json'
    execute([updater,'--apply','--target',root,'--report',report],env,1)
    assert '不匹配' in json.loads(report.read_text(encoding='utf-8'))['error']
    (root/'build-manifest.json').write_bytes(old_manifest);results['wrongVersionRejected']=True
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR];kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.ReleaseMutex.argtypes=[wintypes.HANDLE];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    mutex_name='Local\\InfoLiteracyToolbox-'+hashlib.sha256((str(root.resolve())+'\\').lower().encode()).hexdigest().upper()
    handle=kernel.CreateMutexW(None,True,mutex_name);assert handle
    try: assert '仍在运行' in apply('running',expected=1)['error']
    finally: kernel.ReleaseMutex(handle);kernel.CloseHandle(handle)
    results['runningApplicationRejected']=True
    damaged=destination/'损坏升级.exe';data=bytearray(updater.read_bytes());offset=data.find(b'PK\x03\x04');assert offset>=0;data[offset+40]^=1;damaged.write_bytes(data)
    assert '校验失败' in apply('damaged',damaged,1)['error'];results['damagedPayloadRejected']=True
    assert hashes(root,personal)==saved_personal and database_state(db)==saved_state

    print('Force a validation failure and verify rollback',flush=True)
    db.write_bytes(b'controlled invalid sqlite database')
    corrupt_before=db.read_bytes()
    failed=apply('rollback',expected=1)
    assert '已恢复升级前' in failed['error'],failed
    assert db.read_bytes()==corrupt_before
    assert hashes(root,[row['path'] for row in old_files])==program_before
    assert hashes(root,personal)==saved_personal
    previous_paths={row['path'] for row in old_files}
    for item in description['files']:
        if item['path'] not in previous_paths:
            assert not (root/item['path']).exists()
    results['failedUpgradeRolledBack']=True
    db.write_bytes(saved_db)

    print('Upgrade the real old version and verify every retained record',flush=True)
    result=apply('successful')
    assert json.loads((root/'build-manifest.json').read_text(encoding='utf-8'))['version']==target_version
    assert hashes(root,personal)==saved_personal
    assert database_state(db)==saved_state
    if saved_favorites is not None:
        assert favorite_state(db)==saved_favorites
        results['preexistingFavoritesPreserved']=True
    assert json.loads((Path(result['backup'])/'journal.json').read_text(encoding='utf-8'))['status']=='committed'
    results['personalFilesPreserved']=True;results['usersQuestionsScoresPreserved']=True
    drill_state=None
    def drill_snapshot():
        with closing(sqlite3.connect(db)) as connection:
            tables=['drill_rounds','drill_items','wrong_questions']
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='favorite_questions'").fetchone():
                tables.append('favorite_questions')
            return {name:connection.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall() for name in tables}
    if (root/'02_淘汰赛模考/drill.py').is_file():
        drill_fixture=r'''
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'02_淘汰赛模考'))
from app import create_app,get_db
app=create_app();client=app.test_client()
client.post('/login',data={'username':'升级保留用户','password':'portable-password'})
state=client.post('/api/drill/start',json={'mode':'all'}).json['round']
q=state['question']
with app.app_context(): correct=json.loads(get_db().execute('SELECT answer FROM questions WHERE id=?',(q['id'],)).fetchone()[0])
wrong=next((option['key'] for option in q['options'] if option['key'] not in correct),q['options'][0]['key'])
assert client.post(f"/api/drill/{state['id']}/answer",json={'index':0,'answer':[wrong]}).status_code==200
assert client.get('/api/drill/wrongs').json['total']==1
if 'favorites' in app.blueprints:
    assert client.post(f"/api/favorites/{q['id']}").status_code==200
    assert any(row['id']==q['id'] for row in client.get('/api/favorites').json['items'])
    # Favorite review must not master an existing wrong question.
    assert client.post(f"/api/favorites/{q['id']}/answer",json={'answer':correct}).json['is_correct']
    assert client.post(f"/api/favorites/{q['id']}/reveal").status_code==200
    assert client.get('/api/drill/wrongs').json['total']==1
'''
        execute([python,'-B','-c',drill_fixture,root],env)
        drill_state=drill_snapshot()

    rules_fixture=r'''
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'02_淘汰赛模考'))
from app import create_app,get_db
app=create_app();client=app.test_client();client.post('/login',data={'username':'升级保留用户','password':'portable-password'})
rules={mode:{kind:{'count':1,'correct':3.5 if mode=='personal' else 7,'wrong':-0.5,'unanswered':-0.25}
             for kind in ('single','multi','judge')} for mode in ('personal','team')}
assert client.post('/api/exam-settings',json=rules).status_code==200
assert client.post('/api/exam-timing',json={'personal':2,'team':3,'training_personal':0,'training_team':0,'simulation':0}).status_code==200
aid=client.post('/training/personal/start').json['attempt_id']
with app.app_context():answer=json.loads(get_db().execute('SELECT q.answer FROM questions q JOIN attempt_questions aq ON aq.question_id=q.id WHERE aq.attempt_id=? AND aq.position=0',(aid,)).fetchone()[0])
assert client.post(f'/api/attempt/{aid}/answer',json={'index':0,'answer':answer}).status_code==200
assert client.post(f'/api/attempt/{aid}/advance',json={'index':0,'skip':False}).status_code==200
assert client.post(f'/api/attempt/{aid}/advance',json={'index':1,'skip':True}).status_code==200
'''
    execute([python,'-B','-c',rules_fixture,root],env)

    # New website edits saved after an interrupted update must also survive
    # recovery back through a base version that did not know this feature.
    overlay={'version':1,'nextId':100002,'overrides':{'1':{'title':'升级后自定义网站名称'}},
             'custom':[{'id':100001,'title':'升级后手动资料','url':'https://example.invalid/preserved-resource'}]}
    (reports/'resource-customizations.json').write_text(json.dumps(overlay,ensure_ascii=False),encoding='utf-8')
    catalog=json.loads((root/'03_50知识点检验/02_网站检测工具/data/resources.json').read_text(encoding='utf-8'))
    (reports/'resource-catalog-state.json').write_text(json.dumps({'version':1,'urls':{str(row['id']):row['url'] for row in catalog+overlay['custom']}},ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
    (reports/'resource-url-history.json').write_text(json.dumps({'version':1,'entries':[]}),encoding='utf-8')
    personal.extend('03_50知识点检验/02_网站检测工具/reports/'+name for name in
                    ('resource-customizations.json','resource-catalog-state.json','resource-url-history.json'))
    saved_personal=hashes(root,personal)

    print('Recover a persisted incomplete journal, then upgrade again',flush=True)
    journal_file=Path(result['backup'])/'journal.json'
    journal=json.loads(journal_file.read_text(encoding='utf-8'));journal['status']='validating';journal_file.write_text(json.dumps(journal,ensure_ascii=False),encoding='utf-8')
    # The original v1 launcher might still be present at an early interruption.
    # Simulate work saved after that interruption; recovery must not erase it.
    with closing(sqlite3.connect(db)) as connection:
        connection.execute("INSERT INTO users(username,password_hash,is_admin) VALUES('中断后新增用户','controlled-test-hash',0)")
        connection.commit()
    saved_state=database_state(db)
    pending=destination/'pending-update.json'
    execute([root/'AI信息素养工具箱.exe','--check',pending],env,1)
    assert '未完成的离线升级' in json.loads(pending.read_text(encoding='utf-8'))['error']
    results['pendingUpgradeBlocksLauncher']=True
    result=apply('interrupted-recovery')
    assert hashes(root,personal)==saved_personal and database_state(db)==saved_state
    if drill_state is not None:assert drill_snapshot()==drill_state
    assert json.loads(journal_file.read_text(encoding='utf-8'))['status']=='rolled-back'
    assert result['recoveredDataCopies'] and (Path(result['recoveredDataCopies'][0])/'02_淘汰赛模考/data/platform.db').is_file()
    results['interruptedUpgradeRecovered']=True
    results['newDataAfterInterruptionPreserved']=True
    print('Resume an interrupted data rollback from its complete snapshot',flush=True)
    restoring_file=Path(result['backup'])/'journal.json'
    restoring=json.loads(restoring_file.read_text(encoding='utf-8'))
    restoring.update(status='restoring-data',restoringSnapshot=True)
    restoring_file.write_text(json.dumps(restoring,ensure_ascii=False),encoding='utf-8')
    db.unlink()  # The directory still exists, as it would during a partial restore.
    result=apply('interrupted-data-restore')
    assert database_state(db)==saved_state and hashes(root,personal)==saved_personal
    if drill_state is not None:assert drill_snapshot()==drill_state
    assert json.loads(restoring_file.read_text(encoding='utf-8'))['status']=='rolled-back'
    results['interruptedRollbackRestoredSnapshot']=True
    duplicate=destination/'duplicate.json'
    execute([updater,'--apply','--target',root,'--report',duplicate],env,1)
    assert '无需重复' in json.loads(duplicate.read_text(encoding='utf-8'))['error']
    results['duplicateUpgradeRejected']=True

    print('Start the upgraded native launcher and exercise incremental questions',flush=True)
    execute([root/'AI信息素养工具箱.exe','--check',destination/'new-check.json'],env)
    assert json.loads((destination/'new-check.json').read_text(encoding='utf-8'))['passed']
    assert json.loads((destination/'new-check.json').read_text(encoding='utf-8'))['checker']['total']==198
    results['customWebsiteEditsPreservedThroughRecovery']=True
    execute([python,'-B','-c',r'''
import sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'02_淘汰赛模考'))
from app import create_app
client=create_app().test_client();client.post('/login',data={'username':'升级保留用户','password':'portable-password'})
assert client.get('/api/exam-settings').json['personal']['single']['correct']==3.5
assert client.get('/api/exam-timing').json=={'personal':2,'team':3,'training_personal':0,'training_team':0,'simulation':0}
paper=client.get('/api/current').json['attempt']
assert paper['question_count']==3 and paper['current_position']==2 and paper['max_score']==10.5
assert paper['scoring_rules']['single']['unanswered']==-0.25
assert paper['time_limit_minutes']==0 and paper['deadline'] is None
''',root],env)
    results['customExamSettingsAndActivePaperPreservedThroughRecovery']=True
    results['customTimingSettingsPreservedThroughRecovery']=True
    assert hashes(root,personal)==saved_personal and database_state(db)==saved_state
    if drill_state is not None:
        assert drill_snapshot()==drill_state
        results['drillProgressAndWrongHistoryPreserved']=True
        if 'favorite_questions' in drill_state:
            results['favoritesPreservedAndReviewIndependent']=True
    results['upgradedServicesStart']=True
    added={'type':'single','stem':'升级新增题目验证：不覆盖原有题库','options':['甲','乙'],'answer':'A','source':'升级测试'}
    seed=root/'02_淘汰赛模考/data/source_questions.json';seed.write_text(json.dumps([added],ensure_ascii=False),encoding='utf-8')
    for index in range(2): execute([python,'-B',root/'02_淘汰赛模考/upgrade_data.py','--seed','source_questions.json'],env)
    state=database_state(db)
    assert len(state['questions'])==len(saved_state['questions'])+1
    assert state['questions'][:-1]==saved_state['questions']
    for table in ('users','attempts','attempt_questions'):assert state[table]==saved_state[table]
    results['incrementalQuestionImportIdempotent']=True
    results.update(passed=True,oldArchiveHash=hashlib.sha256(old_zip.read_bytes()).hexdigest(),
                   changedFiles=result['changedFiles'],sourceVersion=description['fromVersion'],targetVersion=target_version,
                   preservedQuestionCount=len(saved_state['questions']),preservedUsers=len(saved_state['users']),
                   preservedAttempts=len(saved_state['attempts']),systemPythonAndNodeOnPath=False)
    (destination/'离线升级验证结果.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--old',type=Path,required=True);parser.add_argument('--update',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();verify(args.old.resolve(),args.update.resolve(),args.destination.resolve())
