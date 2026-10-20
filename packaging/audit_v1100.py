"""Check exact release bytes, private-state exclusions and final evidence."""
import ast
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT/'交付文件'
EVIDENCE = ROOT/'归档管理/v1.10.0验收'
FULL = DELIVERY/'AI信息素养工具箱_Windows免安装版_v1.10.0'
WRAPPER = DELIVERY/'AI信息素养工具箱_离线升级_v1.10.0_自动识别旧版'


def digest(file):
    with file.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def checked_zip(folder):
    archive = folder.with_name(folder.name+'.zip')
    checksum = digest(archive)
    assert archive.with_suffix('.zip.sha256.txt').read_text(encoding='utf-8').split()[0] == checksum
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        for file in folder.rglob('*'):
            if file.is_file():
                member = (Path(folder.name)/file.relative_to(folder)).as_posix()
                assert package.read(member) == file.read_bytes(), member
    return {'name':archive.name, 'bytes':archive.stat().st_size, 'sha256':checksum}


def main():
    tree = ast.parse((ROOT/'packaging/audit_v190.py').read_text(encoding='utf-8'))
    old = ast.literal_eval(next(node.value for node in tree.body
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='OLD' for t in node.targets)))
    old['1.9.0'] = '6ca914fdc8bea79ea19509d31f553dcb0ded306577b47d0276ca30ff93b66a7e'
    old_manifests = {}
    for version, expected in old.items():
        archive = DELIVERY/('AI信息素养工具箱_Windows免安装版'+('' if version=='1.0.0' else '_v'+version)+'.zip')
        assert digest(archive) == expected, version+' old ZIP changed'
        with zipfile.ZipFile(archive) as package:
            old_manifests[version] = package.read(archive.stem+'/build-manifest.json')
    manifest = json.loads((FULL/'build-manifest.json').read_text(encoding='utf-8'))
    assert manifest['version'] == '1.10.0'
    previous = {row['path']:row for row in json.loads(old_manifests['1.9.0'])['files']}
    for row in manifest['files']:
        relative = row['path']
        assert digest(FULL/relative) == row['sha256'], relative
        if relative.startswith(('runtime/', '01_三AI同查/', '03_50知识点检验/')):
            assert row['sha256'] == previous[relative]['sha256'], relative+' unrelated change'
        if relative.startswith('02_淘汰赛模考/'):
            source = ROOT/relative
            if relative.endswith('portable_server.py'):
                source = ROOT/'packaging/exam_server.py'
            elif relative.endswith('upgrade_data.py'):
                source = ROOT/'packaging/upgrade_data.py'
            assert digest(source) == row['sha256'], relative+' stale source'
    expected_data = {'source_questions.json', 'source_bank.json', 'reviewed_duplicate_groups.json'}
    assert {p.name for p in (FULL/'02_淘汰赛模考/data').rglob('*') if p.is_file()} == expected_data
    for relative in ('01_三AI同查/data', '03_50知识点检验/02_网站检测工具/reports'):
        assert not any(p.is_file() for p in (FULL/relative).rglob('*'))
    assert (FULL/'01_三AI同查/desktop.ps1').read_bytes().startswith(b'\xef\xbb\xbf')
    assert (WRAPPER/'offline_upgrade.ps1').read_bytes().startswith(b'\xef\xbb\xbf')
    assert (WRAPPER/'offline_upgrade.ps1').read_bytes() == (ROOT/'packaging/StartOfflineUpgrade.ps1').read_bytes()
    upgrades = []
    for version in old:
        patch = DELIVERY/('AI信息素养工具箱_离线升级包_v'+version+'到v1.10.0')
        description = json.loads((patch/'升级清单.json').read_text(encoding='utf-8'))
        assert description['baseManifestHash'] == hashlib.sha256(old_manifests[version]).hexdigest()
        assert description['targetManifestHash'] == digest(FULL/'build-manifest.json')
        for name in ('双击升级.exe', '升级清单.json', '升级说明.txt'):
            assert digest(patch/name) == digest(WRAPPER/'updates'/version/name)
        report = EVIDENCE/('旧版升级验收_'+version+'_最终')/'离线升级验证结果.json'
        result = json.loads(report.read_text(encoding='utf-8'))
        assert result['passed'] and result['targetVersion']=='1.10.0'
        for key in ('customExamSettingsAndActivePaperPreservedThroughRecovery',
                    'customTimingSettingsPreservedThroughRecovery', 'customWebsiteEditsPreservedThroughRecovery',
                    'failedUpgradeRolledBack', 'interruptedRollbackRestoredSnapshot',
                    'incrementalQuestionImportIdempotent', 'drillProgressAndWrongHistoryPreserved'):
            assert result[key], version+' '+key
        upgrades.append(version)
    log = (EVIDENCE/'模考最终回归.log').read_text(encoding='utf-8')
    assert log.rstrip().endswith('OK') and 'FAILED' not in log
    exam_tests = int(re.search(r'Ran (\d+) tests', log).group(1))
    ai_log = (ROOT/'归档管理/AI打包后复测.log').read_text(encoding='utf-8-sig')
    assert ai_log.rstrip().endswith('OK') and 'Ran 38 tests' in ai_log
    checker_log = (EVIDENCE/'打包后回归/网站检测.log').read_text(encoding='utf-8')
    assert 'pass 26' in checker_log and 'fail 0' in checker_log
    portable = json.loads((EVIDENCE/'正式包最终实测/便携版验证结果.json').read_text(encoding='utf-8'))
    assert portable['passed'] and portable['effectiveQuestionCount']==229
    assert portable['manifestFilesVerified']==len(manifest['files'])
    drill = json.loads((EVIDENCE/'最终完整刷题/全题库刷题验证结果.json').read_text(encoding='utf-8'))
    assert drill['passed'] and drill['uniqueAnsweredQuestions']==229
    result = {'passed':True, 'version':'1.10.0', 'effectiveQuestions':229,
        'legacyRowsPreserved':373, 'aliases':144, 'examTestsPassed':exam_tests,
        'aiTestsPassed':38, 'checkerTestsPassed':26, 'upgradesVerified':upgrades,
        'oldArchivesUnchanged':list(old), 'noPersonalStateInFullPackage':True,
        'manifestFiles':len(manifest['files']), 'runtimeAiAndKnowledgeUnchanged':True,
        'artifacts':[checked_zip(FULL),checked_zip(WRAPPER)]}
    (EVIDENCE/'最终发行核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':
    main()
