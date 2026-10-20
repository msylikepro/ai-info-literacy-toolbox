"""Validate shipped archives, v1.8 program hashes and nine verified updates."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DELIVERY=ROOT/'交付文件'
EVIDENCE=ROOT/'00_整理记录/自定义模考验证_2026-10-17'
OLD={
 '1.0.0':'86f26d7a1d2d33a3f6adb105d4932510db20d162c8b539a3630885bf450923f6',
 '1.1.0':'6cb6a6e85ef748adb4d676dbf37c51e37940fd6e7183219f8dd9106b3d263cc7',
 '1.2.0':'5ac18a0fe7bf8cf6b6b912a7199a906e005fba4a449e33fc8dbd1109ca9e72bb',
 '1.3.0':'6c90064cdbb4ec3c2350189eee34be8cabda9c9e9dcad4c66fdec8e1a95002c3',
 '1.4.0':'fcc0d8edd695fe8590bf7c0e86bbac80f9e896996989336addfde294ced701bd',
 '1.4.1':'0d59884babcf965b153fcd6329a57bd50f4434a131bf4d386de0e6d0a60d309a',
 '1.5.0':'753e4a152a407d444e9ac2993f691ef7a060a0e5cf414467120c519fc3705456',
 '1.6.0':'51992a1b059f70c6af976bafde2b79c4570418b6af067db7ffc671237af0054f',
 '1.7.0':'d93ea13a47c2f631c63e7e904356ea1f55e96e8f675e0ea8e19418b7e86dca0d'}
def digest(file):
    with file.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
for version,expected in OLD.items():
    archive=DELIVERY/('AI信息素养工具箱_Windows免安装版'+('' if version=='1.0.0' else '_v'+version)+'.zip')
    assert digest(archive)==expected,version+' old archive changed'
folder=DELIVERY/'AI信息素养工具箱_Windows免安装版_v1.8.0'
manifest=json.loads((folder/'build-manifest.json').read_text(encoding='utf-8'))
assert manifest['version']=='1.8.0'
for item in manifest['files']:assert digest(folder/item['path'])==item['sha256'],item['path']
for item in manifest['files']:
    if item['path'].startswith('runtime/'):
        assert digest(folder/item['path'])==digest(DELIVERY/'AI信息素养工具箱_Windows免安装版_v1.7.0'/item['path']),item['path']+' unexpected runtime change'
for relative in ('01_三AI同查/data','02_淘汰赛模考/data','03_50知识点检验/02_网站检测工具/reports'):
    names={file.name for file in (folder/relative).rglob('*') if file.is_file()}
    assert names==({'source_questions.json','source_bank.json'} if relative.startswith('02_') else set()),names
for relative in ('02_淘汰赛模考/app.py','02_淘汰赛模考/exam_rules.py','02_淘汰赛模考/static/exam_rules.js',
                 '02_淘汰赛模考/templates/home.html','02_淘汰赛模考/templates/exam.html','02_淘汰赛模考/templates/simulation.html',
                 '02_淘汰赛模考/static/style.css'):
    assert digest(ROOT/relative)==digest(folder/relative),relative+' stale build'
wrapper=DELIVERY/'AI信息素养工具箱_离线升级_v1.8.0_自动识别旧版'
archive=wrapper.with_name(wrapper.name+'.zip')
with zipfile.ZipFile(archive) as package:
    assert package.testzip() is None
    for file in wrapper.rglob('*'):
        if file.is_file():assert package.read((Path(wrapper.name)/file.relative_to(wrapper)).as_posix())==file.read_bytes()
upgrades=[]
for version in OLD:
    patch=DELIVERY/('AI信息素养工具箱_离线升级包_v'+version+'到v1.8.0')
    for name in ('双击升级.exe','升级清单.json','升级说明.txt'):assert digest(patch/name)==digest(wrapper/'updates'/version/name)
    candidates=sorted(EVIDENCE.glob('旧版升级验收_'+version+'*/离线升级验证结果.json'))
    assert candidates,'Missing verification for '+version
    result=json.loads(candidates[-1].read_text(encoding='utf-8'))
    assert result['passed'] and result['customExamSettingsAndActivePaperPreservedThroughRecovery']
    assert result['customWebsiteEditsPreservedThroughRecovery']
    upgrades.append({'source':version,'passed':True,'evidence':str(candidates[-1].relative_to(EVIDENCE))})
artifacts=[]
for file in (folder.with_name(folder.name+'.zip'),archive):
    checksum=digest(file);assert file.with_suffix('.zip.sha256.txt').read_text(encoding='utf-8').split()[0]==checksum
    artifacts.append({'name':file.name,'bytes':file.stat().st_size,'sha256':checksum})
for name,count in (('01_三AI同查',38),('02_淘汰赛模考',47)):
    log=(EVIDENCE/'打包后回归'/(name+'.log')).read_text(encoding='utf-8')
    assert f'Ran {count} tests' in log and log.rstrip().endswith('OK'),name+' regression failed'
checker_log=(EVIDENCE/'打包后回归/网站检测.log').read_text(encoding='utf-8')
assert 'pass 26' in checker_log and 'fail 0' in checker_log
browser=json.loads((EVIDENCE/'打包后浏览器/自定义题数分值浏览器验证.json').read_text(encoding='utf-8'))
assert browser['passed'] and not browser['pageErrors']
portable=json.loads((EVIDENCE/'正式包实测/便携版验证结果.json').read_text(encoding='utf-8'))
assert portable['passed'] and portable['manifestFilesVerified']==len(manifest['files'])
result={'passed':True,'oldArchivesUnchanged':list(OLD),'manifestFiles':len(manifest['files']),
        'upgrades':upgrades,'noPersonalStateInFullPackage':True,'wrapperMatchesVerifiedUpdates':True,
        'runtimeUnchangedFromV170':True,'moduleTestsPassed':111,'packagedBrowserPassed':True,'artifacts':artifacts}
(EVIDENCE/'最终发行核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True))
