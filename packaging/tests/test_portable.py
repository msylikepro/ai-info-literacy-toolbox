"""Checks that a shareable build preserves content without copying private state."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import build_portable
except ModuleNotFoundError:
    build_portable = None


class DistributionContentTest(unittest.TestCase):
    def test_shareable_copy_excludes_credentials_scores_and_audits(self):
        self.assertIsNotNone(build_portable, 'The portable build pipeline is not implemented')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / '原文件'
            out = Path(folder) / '给队友的文件'
            fixtures = {
                '01_三AI同查/solver.py': 'print("solver")',
                '01_三AI同查/desktop.ps1': "param([Alias('CodexProxy')][string]$GptProxy = 'http://127.0.0.1:7897')",
                '01_三AI同查/run_solver.ps1': "'.venv\\Scripts\\python.exe'",
                '01_三AI同查/configure_apis.ps1': '# config',
                '01_三AI同查/thinking_config.ps1': '# thinking settings',
                '01_三AI同查/configure_openai.ps1': '# legacy GPT config',
                '01_三AI同查/data/api-keys.dpapi.json': 'PRIVATE KEY',
                '02_淘汰赛模考/app.py': '# exam',
                '02_淘汰赛模考/importer.py': '# importer',
                '02_淘汰赛模考/drill.py': '# question drill',
                '02_淘汰赛模考/favorites.py': '# independent favorite review',
                '02_淘汰赛模考/question_bank.py': '# read-only bank browser',
                '02_淘汰赛模考/exam_rules.py': '# configurable exam rules',
                '02_淘汰赛模考/distillation.py': '# reviewed question duplicates',
                '02_淘汰赛模考/data/reviewed_duplicate_groups.json': '{"groups": []}',
                '02_淘汰赛模考/templates/home.html': 'exam page',
                '02_淘汰赛模考/static/app.js': '// client',
                '02_淘汰赛模考/data/source_bank.json': '[{"stem":"题库"}]',
                '02_淘汰赛模考/data/source_questions.json': '[]',
                '02_淘汰赛模考/data/platform.db': 'PRIVATE SCORES',
                '02_淘汰赛模考/data/admin_credentials.txt': 'PRIVATE PASSWORD',
                '02_淘汰赛模考/data/.secret_key': 'PRIVATE SESSION KEY',
                '02_淘汰赛模考/data/import_test.json': 'PRIVATE IMPORT',
                '03_50知识点检验/02_网站检测工具/server.cjs': '// checker',
                '03_50知识点检验/02_网站检测工具/public/index.html': 'checker page',
                '03_50知识点检验/02_网站检测工具/data/resources.json': '[]',
                '03_50知识点检验/02_网站检测工具/reports/manual-audits.json': 'PRIVATE AUDIT',
                '03_50知识点检验/02_网站检测工具/reports/resource-customizations.json': 'PRIVATE WEBSITES',
                '03_50知识点检验/02_网站检测工具/reports/resource-catalog-state.json': 'PRIVATE CATALOG STATE',
                '03_50知识点检验/02_网站检测工具/reports/resource-url-history.json': 'PRIVATE URL HISTORY',
                '03_50知识点检验/01_网址清单/50个知识点_网址清单.html': 'knowledge page',
                '03_50知识点检验/03_PDF参考资料/中文资料.pdf': '%PDF-example',
                '03_50知识点检验/03_PDF参考资料/_资料索引.html': 'pdf index',
                '03_50知识点检验/04_网址导航网站/knowledge-links/dist/index.html': 'navigation page',
            }
            for name, content in fixtures.items():
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(content, encoding='utf-8')
            build_portable.stage_application(root, out)
            files = [p for p in out.rglob('*') if p.is_file()]
            self.assertTrue(files)
            for file in files:
                self.assertNotIn('PRIVATE', file.read_text(encoding='utf-8-sig'), str(file))
            self.assertEqual((out / '02_淘汰赛模考/data/source_bank.json').read_text(encoding='utf-8'), '[{"stem":"题库"}]')
            self.assertTrue((out / '02_淘汰赛模考/exam_rules.py').is_file())
            self.assertTrue((out / '02_淘汰赛模考/distillation.py').is_file())
            self.assertEqual((out / '02_淘汰赛模考/data/reviewed_duplicate_groups.json').read_text(encoding='utf-8'), '{"groups": []}')
            self.assertTrue((out / '03_50知识点检验/03_PDF参考资料/中文资料.pdf').is_file())
            self.assertTrue((out / '03_50知识点检验/02_网站检测工具/reports').is_dir())
            self.assertNotIn('7897', (out / '01_三AI同查/desktop.ps1').read_text(encoding='utf-8-sig'))
            self.assertIn('runtime', (out / '01_三AI同查/run_solver.ps1').read_text(encoding='utf-8-sig'))
            # Building must never modify the original files or private state.
            for name, content in fixtures.items():
                self.assertEqual((root / name).read_text(encoding='utf-8'), content)


if __name__ == '__main__':
    unittest.main()
