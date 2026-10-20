"""Produce a self-contained native updater containing only release differences."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
PRODUCT_ID = 'ai-info-literacy-toolbox'
EXE_NAME = 'AI信息素养工具箱.exe'
SEEDS = {'02_淘汰赛模考/data/source_questions.json', '02_淘汰赛模考/data/source_bank.json'}
CURATED_DATA = SEEDS | {'02_淘汰赛模考/data/reviewed_duplicate_groups.json'}


def digest(file):
    with Path(file).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_path(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or name.startswith('/'):
        raise ValueError('Unsafe release path: ' + str(name))
    parts = name.split('/')
    if any(not p or p in ('.','..') or p.endswith((' ','.')) or any(ord(c)<32 for c in p)
           or re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',p,re.I) for p in parts):
        raise ValueError('Unsafe release path: ' + name)
    lower = name.casefold()
    if (lower.startswith(('01_三ai同查/data/', '02_淘汰赛模考/data/')) and name not in CURATED_DATA
        or lower.startswith(('03_50知识点检验/02_网站检测工具/reports/','logs/','update-backups/'))
        or lower in ('build-manifest.json',)):
        raise ValueError('Protected user data in release manifest: ' + name)
    return name


def load_release(root):
    root = Path(root)
    data = json.loads((root/'build-manifest.json').read_text(encoding='utf-8'))
    if data.get('product') != 'AI信息素养工具箱_Windows免安装版':
        raise ValueError('This is not an info-literacy release')
    records = {}
    folded = set()
    for item in data['files']:
        name = validate_path(item['path'])
        if name.casefold() in folded:
            raise ValueError('Duplicate release path: ' + name)
        folded.add(name.casefold())
        file = root/name
        if not file.is_file() or digest(file) != item['sha256']:
            raise ValueError('Release hash mismatch: ' + name)
        records[name] = item
    if EXE_NAME not in records:
        raise ValueError('The release launcher is missing')
    return data, records


def describe_update(old_root, new_root):
    old, before = load_release(old_root)
    new, after = load_release(new_root)
    old_version, new_version = old.get('version','1.0.0'), new.get('version','1.0.0')
    def version(value):
        if not re.fullmatch(r'\d+\.\d+\.\d+', value): raise ValueError('Use a numeric x.y.z version')
        return tuple(map(int,value.split('.')))
    if version(new_version) <= version(old_version):
        raise ValueError('Target version must be newer than the base release')
    changed = [item for name,item in after.items() if name not in before or before[name]['sha256'] != item['sha256']]
    # Existing audit records refer to stable numeric resource IDs.
    resources = '03_50知识点检验/02_网站检测工具/data/resources.json'
    if resources in before and resources in after and before[resources]['sha256'] != after[resources]['sha256']:
        prior = {r['id']:r['url'] for r in json.loads((Path(old_root)/resources).read_text(encoding='utf-8'))}
        migration_path='03_50知识点检验/02_网站检测工具/data/resource-migrations.json'
        migrations=[]
        if migration_path in after:
            document=json.loads((Path(new_root)/migration_path).read_text(encoding='utf-8'))
            if document.get('version')!=1 or not isinstance(document.get('changes'),list):
                raise ValueError('Invalid resource URL migration document')
            migrations=document['changes']
        for row in json.loads((Path(new_root)/resources).read_text(encoding='utf-8')):
            if row['id'] in prior and prior[row['id']] != row['url']:
                permitted=any(change.get('id')==row['id'] and change.get('from')==prior[row['id']]
                              and change.get('to')==row['url'] for change in migrations if isinstance(change,dict))
                if not permitted:
                    raise ValueError('Existing website resource IDs cannot be reused without an explicit URL migration')
    return {'format':1,'productId':PRODUCT_ID,'fromVersion':old_version,'toVersion':new_version,
            'baseManifestHash':digest(Path(old_root)/'build-manifest.json'),
            'targetManifestHash':digest(Path(new_root)/'build-manifest.json'),
            'files':changed,'delete':sorted(set(before)-set(after)),
            'seedFiles':sorted(SEEDS & {x['path'] for x in changed})}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--new', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    description = describe_update(args.base,args.new)
    if args.output.exists(): raise SystemExit('Output exists; use a new directory')
    args.output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='literacy-update-build-') as temp:
        work = Path(temp)
        payload = work/'payload.zip'
        with zipfile.ZipFile(payload,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as package:
            package.writestr('update.json',json.dumps(description,ensure_ascii=False))
            package.write(args.base/'build-manifest.json','base-manifest.json')
            package.write(args.new/'build-manifest.json','target-manifest.json')
            for item in description['files']:
                package.write(args.new/item['path'],'files/'+item['path'])
        constant = work/'Bundle.cs'
        constant.write_text('static class Bundle { public const string Hash = "'+digest(payload)+'"; }',encoding='utf-8')
        compiler = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        executable = args.output/'双击升级.exe'
        subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+','/codepage:65001',
            '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll',
            '/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll',
            '/resource:'+str(payload)+',payload.zip','/out:'+str(executable),str(HERE/'OfflineUpdater.cs'),str(HERE/'ManagedProcesses.cs'),str(constant)],check=True)
    note = f'''AI＋信息素养工具箱 · 离线升级包 {description['fromVersion']} → {description['toVersion']}

1. 先完成答题并关闭原工具箱；保持原文件夹完整。
2. 将本升级包完整解压到原工具箱文件夹以外的位置。
3. 双击「双击升级.exe」，选择原「AI信息素养工具箱.exe」所在的文件夹，点击「开始升级」。
4. 成功后仍从原文件夹打开工具箱；无需重装，也不用重填本机 API 配置。

程序会验证原版本和升级文件、备份本地数据，只替换本次变化的程序与资料。
保留 API 配置、账号、密码、成绩、自建题目、刷题进度、错题、收藏及手动网址修改。
保留无关网址的检测和审核记录；本次变更网址的旧检测和审核信息会归档，新入口需重新检测。
失败会恢复到升级前状态；中途断电或关闭时，再运行同一个升级程序恢复。
备份与结果在原工具箱的 update-backups 文件夹中。备份包含个人数据，请勿发送给别人。
题库源文件有变化时采用增量导入，保留原题目编号、自建题目及已有成绩。
此升级包只适用于所标注的原版本；已更新、版本不匹配或程序文件被修改时会拒绝覆盖。
不需要联网、管理员权限，也不需要另外安装 Python 或 Node.js。
升级窗口显示的文件校验用于发现损坏；请仅运行由你信任的发布者提供的升级 EXE。
'''
    (args.output/'升级说明.txt').write_text(note,encoding='utf-8-sig')
    (args.output/'升级清单.json').write_text(json.dumps(description,ensure_ascii=False,indent=2),encoding='utf-8')
    archive = args.output.parent / (args.output.name + '.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as package:
        for file in args.output.iterdir(): package.write(file,Path(args.output.name)/file.name)
    archive.with_suffix('.zip.sha256.txt').write_text(digest(archive)+'  '+archive.name+'\n',encoding='utf-8')
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'changedFiles':len(description['files']),
                      'fromVersion':description['fromVersion'],'toVersion':description['toVersion']},ensure_ascii=True))


if __name__ == '__main__': main()
