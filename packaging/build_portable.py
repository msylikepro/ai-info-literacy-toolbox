"""Build the Windows x64 distribution from explicit, shareable inputs only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
PACKAGE_NAME = 'AI信息素养工具箱_Windows免安装版'
EXE_NAME = 'AI信息素养工具箱.exe'
PACKAGES = ('flask', 'werkzeug', 'jinja2', 'markupsafe', 'click', 'itsdangerous',
            'blinker', 'openpyxl', 'et_xmlfile')


def copy_tree(source, target):
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo', 'tests', '.DS_Store'))


def stage_application(source, target):
    """Allowlist program files and seed data; never copy users or credentials."""
    source, target = Path(source), Path(target)
    ai = '01_三AI同查'
    for name in ('solver.py', 'desktop.ps1', 'run_solver.ps1', 'configure_apis.ps1', 'configure_openai.ps1', 'thinking_config.ps1'):
        src = source / ai / name
        dest = target / ai / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith('.ps1'):
            content = src.read_text(encoding='utf-8-sig')
            if name == 'run_solver.ps1':
                old = '.venv\\Scripts\\python.exe'
                if old not in content:
                    raise ValueError('The solver interpreter lookup changed; review packaging adaptation')
                content = content.replace(old, 'runtime\\python\\python.exe')
            elif name == 'desktop.ps1':
                old = "[string]$GptProxy = 'http://127.0.0.1:7897'"
                if old not in content:
                    raise ValueError('The desktop proxy default changed; review packaging adaptation')
                content = content.replace(old, "[string]$GptProxy = ''")
            # Windows PowerShell 5.1 requires a BOM for Chinese scripts.
            dest.write_text(content, encoding='utf-8-sig')
        else:
            shutil.copy2(src, dest)
    (target / ai / 'data').mkdir(parents=True, exist_ok=True)
    exam = '02_淘汰赛模考'
    for name in ('app.py', 'importer.py', 'drill.py', 'favorites.py', 'question_bank.py', 'exam_rules.py', 'distillation.py'):
        dest = target / exam / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / exam / name, dest)
    for name in ('templates', 'static'):
        copy_tree(source / exam / name, target / exam / name)
    (target / exam / 'data').mkdir(parents=True, exist_ok=True)
    for name in ('source_questions.json', 'source_bank.json', 'reviewed_duplicate_groups.json'):
        shutil.copy2(source / exam / 'data' / name, target / exam / 'data' / name)
    knowledge = '03_50知识点检验'
    checker = Path(knowledge) / '02_网站检测工具'
    (target / checker).mkdir(parents=True, exist_ok=True)
    for file in (source / checker).glob('*.cjs'):
        shutil.copy2(file, target / checker / file.name)
    for name in ('public', 'data'):
        copy_tree(source / checker / name, target / checker / name)
    (target / checker / 'reports').mkdir(parents=True, exist_ok=True)
    for name in ('01_网址清单', '03_PDF参考资料'):
        copy_tree(source / knowledge / name, target / knowledge / name)
    navigation = Path(knowledge) / '04_网址导航网站' / 'knowledge-links' / 'dist'
    copy_tree(source / navigation, target / navigation)


def stage_runtime(python_home, node_executable, packages_home, target):
    python_target = target / 'runtime' / 'python'
    python_target.mkdir(parents=True)
    # No installer, registry lookup, virtualenv redirector, pip, or user site.
    for pattern in ('python*.exe', 'python*.dll', 'vcruntime*.dll', 'LICENSE*'):
        for file in python_home.glob(pattern):
            shutil.copy2(file, python_target / file.name)
    copy_tree(python_home / 'DLLs', python_target / 'DLLs')
    stdlib = python_target / 'Lib'
    shutil.copytree(python_home / 'Lib', stdlib,
                    ignore=shutil.ignore_patterns('site-packages', '__pycache__', '*.pyc', '*.pyo',
                                                 'ensurepip', 'idlelib', 'tkinter', 'turtledemo', 'test'))
    site = stdlib / 'site-packages'
    site.mkdir()
    for name in PACKAGES:
        copy_tree(packages_home / name, site / name)
        for metadata in packages_home.glob(name + '-*.dist-info'):
            copy_tree(metadata, site / metadata.name)
    # MarkupSafe has a pure Python fallback. Do not ship another Python ABI's extensions.
    for extension in site.rglob('*.pyd'):
        extension.unlink()
    (python_target / 'python._pth').write_text('Lib\nDLLs\nLib/site-packages\nimport site\n', encoding='ascii')
    node_target = target / 'runtime' / 'node'
    node_target.mkdir()
    shutil.copy2(node_executable, node_target / 'node.exe')
    result = subprocess.run([str(node_executable), '-p', 'process.release.name + " " + process.version'],
                            capture_output=True, text=True, check=True)
    return {'python': subprocess.check_output([str(python_target / 'python.exe'), '-B', '-c',
            'import sys; print(sys.version.split()[0])'], text=True).strip(),
            'node': result.stdout.strip()}


def compile_launcher(target):
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    command = [str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
               '/codepage:65001', '/reference:System.Windows.Forms.dll',
               '/reference:System.Drawing.dll', '/reference:System.Web.Extensions.dll',
               '/out:' + str(target / EXE_NAME), str(HERE / 'Launcher.cs'), str(HERE / 'ManagedProcesses.cs')]
    subprocess.run(command, check=True)


def write_manifest(target, versions, version='1.10.0'):
    files = []
    for file in sorted(target.rglob('*')):
        if file.is_file() and file.name != 'build-manifest.json':
            files.append({'path': file.relative_to(target).as_posix(), 'bytes': file.stat().st_size,
                          'sha256': hashlib.file_digest(file.open('rb'), 'sha256').hexdigest()})
    manifest = {'product': PACKAGE_NAME, 'productId': 'ai-info-literacy-toolbox',
                'version': version, 'platform': 'Windows 10/11 x64',
                'runtimes': versions, 'files': files}
    (target / 'build-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    cache = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies'
    parser.add_argument('--python-home', type=Path, default=cache / 'python')
    parser.add_argument('--node', type=Path, default=cache / 'node/bin/node.exe')
    parser.add_argument('--packages', type=Path, default=ROOT / '.venv/Lib/site-packages')
    parser.add_argument('--version', default='1.10.0')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    import re
    if not re.fullmatch(r'\d+\.\d+\.\d+',args.version): raise SystemExit('Use a numeric x.y.z version')
    target = (args.output or ROOT / '交付文件' / (PACKAGE_NAME+'_v'+args.version)).resolve()
    # Refuse overwriting a used distribution or any existing data.
    if target.exists():
        raise SystemExit('Output already exists. Use a new --output directory; existing user data will not be overwritten.')
    for path in (args.python_home / 'python.exe', args.node, args.packages / 'flask/__init__.py'):
        if not path.is_file():
            raise SystemExit('Required build input is missing: ' + str(path))
    target.mkdir(parents=True)
    stage_application(ROOT, target)
    versions = stage_runtime(args.python_home, args.node, args.packages, target)
    shutil.copy2(HERE / 'exam_server.py', target / '02_淘汰赛模考/portable_server.py')
    shutil.copy2(HERE / 'upgrade_data.py', target / '02_淘汰赛模考/upgrade_data.py')
    shutil.copy2(HERE / '使用说明.txt', target / '先读我_使用说明.txt')
    licenses = target / 'licenses'
    licenses.mkdir()
    for file in HERE.glob('license-*'):
        shutil.copy2(file, licenses / file.name)
    compile_launcher(target)
    write_manifest(target, versions, args.version)
    archive = target.parent / (target.name + '.zip')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for file in target.rglob('*'):
            if file.is_file():
                package.write(file, Path(target.name) / file.relative_to(target))
    checksum = hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
    archive.with_suffix('.zip.sha256.txt').write_text(checksum + '  ' + archive.name + '\n', encoding='utf-8')
    print(json.dumps({'folder': str(target), 'zip': str(archive), 'bytes': archive.stat().st_size,
                      'sha256': checksum, 'runtimes': versions}, ensure_ascii=True))


if __name__ == '__main__':
    main()
