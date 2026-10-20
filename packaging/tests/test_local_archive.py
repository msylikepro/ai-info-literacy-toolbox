import importlib.util
from pathlib import Path
import tempfile
import unittest

class LocalArchiveTest(unittest.TestCase):
    def module(self):
        file=Path(__file__).resolve().parents[1]/'local_archive.py'
        self.assertTrue(file.is_file(),'Local archive helper is missing')
        spec=importlib.util.spec_from_file_location('local_archive',file)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_deduplicated_round_trip_preserves_binary_unicode_and_empty_files(self):
        module=self.module()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'来源';root.mkdir()
            (root/'中文.txt').write_text('题库资料',encoding='utf-8')
            (root/'repeat.bin').write_bytes(b'\0\xff'*300)
            (root/'sub').mkdir();(root/'sub/repeat.bin').write_bytes(b'\0\xff'*300)
            (root/'empty').touch();(root/'excluded').mkdir();(root/'excluded/private').write_text('skip')
            archive=Path(folder)/'backup.zip'
            result=module.snapshot(root,archive,{'excluded'})
            self.assertEqual(result['files'],4);self.assertEqual(result['objects'],3)
            self.assertTrue(module.verify(archive)['passed'])
            restored=Path(folder)/'恢复';module.restore(archive,restored)
            for relative in ('中文.txt','repeat.bin','sub/repeat.bin','empty'):
                self.assertEqual((root/relative).read_bytes(),(restored/relative).read_bytes())
            self.assertFalse((restored/'excluded').exists())
            with self.assertRaises(ValueError):module.restore(archive,restored)

    def test_rejects_traversal_absolute_and_windows_device_paths(self):
        module=self.module()
        for value in ('../outside','/absolute','C:/file','folder/../file','folder\\file','CON','a/NUL.txt','a/file.'):
            with self.subTest(value=value),self.assertRaises(ValueError):module.safe_path(value)
