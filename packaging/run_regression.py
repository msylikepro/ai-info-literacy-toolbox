"""Run the existing suites against a disposable extracted distribution."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('distribution', type=Path)
    parser.add_argument('--logs', required=True, type=Path)
    args = parser.parse_args()
    root = args.distribution.resolve()
    source = Path(__file__).resolve().parents[1]
    args.logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    for name in list(env):
        if name.startswith(('OPENAI_', 'QWEN_', 'DASHSCOPE_', 'DEEPSEEK_', 'CODEX_PROXY', 'CHECKER_')):
            env.pop(name, None)
    commands = []
    python = root / 'runtime/python/python.exe'
    for module in ('01_三AI同查', '02_淘汰赛模考'):
        shutil.copytree(source / module / 'tests', root / module / 'tests', dirs_exist_ok=True)
        if module == '01_三AI同查':
            # Keep real UI controls and assertions, but position test-only windows
            # off-screen so background verification does not disturb the user.
            for test_name in ('test_desktop.py','test_images.py'):
                desktop_test=root/module/'tests'/test_name
                contents=desktop_test.read_text(encoding='utf-8')
                contents=contents.replace('$state.Form.Show()',
                    '$state.Form.StartPosition = [Windows.Forms.FormStartPosition]::Manual; '
                    '$state.Form.Location = New-Object Drawing.Point(-15000,-15000); $state.Form.Show()')
                desktop_test.write_text(contents,encoding='utf-8')
        command = [str(python), '-B', '-c',
                   "import sys,unittest;sys.path.insert(0,'.');r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests'));sys.exit(not r.wasSuccessful())"]
        commands.append((module, command, root / module))
    checker = Path('03_50知识点检验/02_网站检测工具')
    shutil.copytree(source / checker / 'tests', root / checker / 'tests', dirs_exist_ok=True)
    commands.append(('网站检测', [str(root / 'runtime/node/node.exe'), '--test',
                    *[str(path.relative_to(root/checker)) for path in sorted((root/checker/'tests').glob('*.test.cjs'))]], root / checker))
    failed = []
    for name, command, cwd in commands:
        print('Running ' + name, flush=True)
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=240)
        (args.logs / (name + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
        print(result.stdout[-3000:] + result.stderr[-5000:], flush=True)
        if result.returncode:
            failed.append(name)
    if failed:
        raise SystemExit('Failed suites: ' + ', '.join(failed))


if __name__ == '__main__':
    main()
