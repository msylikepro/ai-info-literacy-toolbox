import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

@unittest.skipUnless(os.name=='nt','Windows required')
class SharedUpgradeSelectionTest(unittest.TestCase):
    def test_knowledge_update_detects_all_bases_including_thinking_release(self):
        script=Path(__file__).resolve().parents[1]/'StartOfflineUpgrade.ps1'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'AI信息素养工具箱.exe').write_bytes(b'fixture')
            for version in (None,'1.0.0','1.1.0','1.2.0','1.3.0','1.4.0','1.4.1','1.5.0','1.6.0','1.7.0','1.8.0','1.9.0','1.10.0'):
                manifest={'product':'AI信息素养工具箱_Windows免安装版'}
                if version:manifest['version']=version
                (root/'build-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
                process=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-ResolveOnly','-Target',str(root)],capture_output=True,encoding='utf-8',timeout=15)
                self.assertEqual(process.returncode,0,process.stderr)
                result=json.loads(process.stdout.lstrip('\ufeff'))
                self.assertEqual(result['TargetVersion'],'1.10.0')
                self.assertEqual(result['UpdaterRelative'],None if version=='1.10.0' else 'updates\\'+(version or '1.0.0')+'\\双击升级.exe')

    def test_exam_rules_update_recovers_pending_v170_after_target_manifest_written(self):
        script=Path(__file__).resolve().parents[1]/'StartOfflineUpgrade.ps1'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'AI信息素养工具箱.exe').write_bytes(b'fixture')
            (root/'build-manifest.json').write_text(json.dumps({'product':'AI信息素养工具箱_Windows免安装版','version':'1.10.0'},ensure_ascii=False),encoding='utf-8')
            journal=root/'update-backups/transaction/journal.json';journal.parent.mkdir(parents=True)
            journal.write_text(json.dumps({'status':'validating','fromVersion':'1.7.0'}),encoding='utf-8')
            process=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-ResolveOnly','-Target',str(root)],capture_output=True,encoding='utf-8',timeout=15)
            self.assertEqual(process.returncode,0,process.stderr)
            result=json.loads(process.stdout.lstrip('\ufeff'))
            self.assertEqual(result['SourceVersion'],'1.7.0')
            self.assertEqual(result['TargetVersion'],'1.10.0')
            self.assertEqual(result['UpdaterRelative'],'updates\\1.7.0\\双击升级.exe')
    def test_detects_all_supported_bases_and_skips_already_upgraded(self):
        script=Path(__file__).resolve().parents[1]/'StartSharedUpgrade.ps1'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'AI信息素养工具箱.exe').write_bytes(b'fixture')
            for version in (None,'1.0.0','1.1.0','1.2.0','1.3.0'):
                manifest={'product':'AI信息素养工具箱_Windows免安装版'}
                if version:manifest['version']=version
                (root/'build-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
                process=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-ResolveOnly','-Target',str(root)],capture_output=True,encoding='utf-8',timeout=15)
                self.assertEqual(process.returncode,0,process.stderr)
                result=json.loads(process.stdout.lstrip('\ufeff'))
                self.assertEqual(result['SourceVersion'],version or '1.0.0')
                self.assertEqual(result['TargetVersion'],'1.3.0')
                self.assertEqual(result['UpdaterRelative'],None if version=='1.3.0' else 'updates\\'+(version or '1.0.0')+'\\双击升级.exe')

    def test_pending_upgrade_routes_to_its_base_even_with_new_manifest(self):
        script=Path(__file__).resolve().parents[1]/'StartSharedUpgrade.ps1'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'AI信息素养工具箱.exe').write_bytes(b'fixture')
            (root/'build-manifest.json').write_text(json.dumps({'product':'AI信息素养工具箱_Windows免安装版','version':'1.3.0'},ensure_ascii=False),encoding='utf-8')
            journal=root/'update-backups/transaction/journal.json';journal.parent.mkdir(parents=True)
            journal.write_text(json.dumps({'status':'validating','fromVersion':'1.2.0'}),encoding='utf-8')
            process=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-ResolveOnly','-Target',str(root)],capture_output=True,encoding='utf-8',timeout=15)
            self.assertEqual(process.returncode,0,process.stderr)
            result=json.loads(process.stdout.lstrip('\ufeff'))
            self.assertEqual(result['SourceVersion'],'1.2.0')
            self.assertEqual(result['UpdaterRelative'],'updates\\1.2.0\\双击升级.exe')
