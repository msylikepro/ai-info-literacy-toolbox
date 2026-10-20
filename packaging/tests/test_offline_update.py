"""Exercise release comparison against actual file hashes and protected data."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import build_update
except ModuleNotFoundError:
    build_update = None


def manifest(root, version, content):
    files = []
    for name, value in content.items():
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(value)
        files.append({'path':name,'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()})
    data = {'product':'AI信息素养工具箱_Windows免安装版','platform':'Windows 10/11 x64',
            'files':files, 'version':version}
    (root / 'build-manifest.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


class OfflinePackageTest(unittest.TestCase):
    def test_reviewed_question_mapping_is_payload_not_an_importable_seed(self):
        mapping = '02_淘汰赛模考/data/reviewed_duplicate_groups.json'
        with tempfile.TemporaryDirectory() as temp:
            old, new = Path(temp)/'old', Path(temp)/'new'
            manifest(old, '1.9.0', {'AI信息素养工具箱.exe': b'old'})
            manifest(new, '1.10.0', {'AI信息素养工具箱.exe': b'new', mapping: b'{"groups": []}'})
            delta = build_update.describe_update(old, new)
            self.assertIn(mapping, {row['path'] for row in delta['files']})
            self.assertNotIn(mapping, delta['seedFiles'])

    def test_url_migration_requires_exact_id_old_and_new_urls_in_manifested_file(self):
        resource='03_50知识点检验/02_网站检测工具/data/resources.json'
        migration='03_50知识点检验/02_网站检测工具/data/resource-migrations.json'
        old_url='https://www.nmpa.gov.cn/datasearch/home-index.html'
        new_url='https://datasearch.nmpa.gov.cn/datasearch/home-index.html'
        with tempfile.TemporaryDirectory() as temp:
            old,new=Path(temp)/'old',Path(temp)/'new'
            manifest(old,'1.6.0',{'AI信息素养工具箱.exe':b'old',resource:json.dumps([{'id':79,'url':old_url}]).encode()})
            # An explicit migration is allowed, arbitrary ID reuse remains rejected.
            manifest(new,'1.7.0',{'AI信息素养工具箱.exe':b'new',resource:json.dumps([{'id':79,'url':new_url}]).encode(),
                migration:json.dumps({'version':1,'changes':[{'id':79,'from':old_url,'to':new_url}]}).encode()})
            self.assertEqual(build_update.describe_update(old,new)['toVersion'],'1.7.0')
            for change in ({'id':78,'from':old_url,'to':new_url},{'id':79,'from':'https://wrong.invalid/','to':new_url},
                           {'id':79,'from':old_url,'to':'https://wrong.invalid/'}):
                manifest(new,'1.7.0',{'AI信息素养工具箱.exe':b'new',resource:json.dumps([{'id':79,'url':new_url}]).encode(),
                    migration:json.dumps({'version':1,'changes':[change]}).encode()})
                with self.assertRaises(ValueError):build_update.describe_update(old,new)

    def test_delta_carries_changed_files_and_never_personal_state(self):
        self.assertIsNotNone(build_update, 'Offline update package builder is not implemented')
        with tempfile.TemporaryDirectory() as temp:
            old, new = Path(temp)/'old', Path(temp)/'new'
            manifest(old, '1.0.0', {'AI信息素养工具箱.exe':b'old', 'runtime/node/node.exe':b'unchanged', 'obsolete.txt':b'remove'})
            manifest(new, '1.1.0', {'AI信息素养工具箱.exe':b'new', 'runtime/node/node.exe':b'unchanged', 'new.txt':b'new file'})
            (new/'01_三AI同查/data').mkdir(parents=True)
            (new/'01_三AI同查/data/api-keys.dpapi.json').write_text('PRIVATE')
            delta = build_update.describe_update(old, new)
            self.assertEqual({x['path'] for x in delta['files']}, {'AI信息素养工具箱.exe','new.txt'})
            self.assertEqual(delta['delete'], ['obsolete.txt'])
            self.assertEqual(delta['fromVersion'], '1.0.0')
            self.assertNotIn('PRIVATE', json.dumps(delta))

    def test_modified_release_payload_is_rejected(self):
        self.assertIsNotNone(build_update)
        with tempfile.TemporaryDirectory() as temp:
            old, new = Path(temp)/'old', Path(temp)/'new'
            manifest(old,'1.0.0',{'AI信息素养工具箱.exe':b'old'})
            manifest(new,'1.1.0',{'AI信息素养工具箱.exe':b'new'})
            (new/'AI信息素养工具箱.exe').write_bytes(b'CORRUPTED')
            with self.assertRaisesRegex(ValueError,'hash|哈希'):
                build_update.describe_update(old,new)

    def test_manifest_cannot_target_user_database_or_escape_package(self):
        self.assertIsNotNone(build_update)
        for forbidden in ('../outside.txt','C:/outside.txt','02_淘汰赛模考/data/platform.db',
                          '01_三AI同查/data/api-keys.dpapi.json','03_50知识点检验/02_网站检测工具/reports/latest.json'):
            with self.subTest(path=forbidden), tempfile.TemporaryDirectory() as temp:
                old, new = Path(temp)/'old',Path(temp)/'new'
                manifest(old,'1.0.0',{'AI信息素养工具箱.exe':b'old'})
                manifest(new,'1.1.0',{'AI信息素养工具箱.exe':b'new'})
                data = json.loads((new/'build-manifest.json').read_text(encoding='utf-8'))
                data['files'].append({'path':forbidden,'bytes':1,'sha256':'0'*64})
                (new/'build-manifest.json').write_text(json.dumps(data),encoding='utf-8')
                with self.assertRaises(ValueError): build_update.describe_update(old,new)


if __name__ == '__main__': unittest.main()
