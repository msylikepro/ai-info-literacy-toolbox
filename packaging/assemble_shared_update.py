"""Wrap verified native deltas and an encrypted shared config into one private ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

here=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument('--shared',required=True,type=Path)
parser.add_argument('--updates',required=True,nargs=3,type=Path)
args=parser.parse_args()
target=args.shared.resolve()
assert {p.name for p in target.iterdir()}=={'导入共享API配置.exe','shared-api.enc.json'},'Use a fresh encrypted export folder without a password file'
versions=set()
for folder in args.updates:
    description=json.loads((folder/'升级清单.json').read_text(encoding='utf-8'))
    version=description['fromVersion'];assert version in ('1.0.0','1.1.0','1.2.0') and description['toVersion']=='1.3.0'
    assert version not in versions;versions.add(version)
    destination=target/'updates'/version;destination.mkdir(parents=True)
    for name in ('双击升级.exe','升级说明.txt','升级清单.json'):
        shutil.copy2(folder/name,destination/name)
assert versions=={'1.0.0','1.1.0','1.2.0'}
shutil.copy2(here/'StartSharedUpgrade.ps1',target/'start_upgrade.ps1')
(target/'双击开始升级.bat').write_text('@echo off\r\nstart "" powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start_upgrade.ps1"\r\n',encoding='ascii')
note='''AI＋信息素养工具箱 v1.3.0 · 离线升级与团队共享 API

1. 完整解压本 ZIP 到原工具箱文件夹以外的位置，先关闭原工具箱。
2. 双击「双击开始升级.bat」，选择原 AI信息素养工具箱.exe 所在文件夹。
3. 入口自动识别最初版本、v1.1.0 或 v1.2.0；在打开的升级窗口点击「开始升级」。
4. 成功后关闭升级窗口，自动进入共享 API 导入窗口。已经是 v1.3.0 时直接进入导入。
5. 输入提供者单独发送的导入口令，点击「导入并覆盖配置」。成功后从原目录打开工具箱。
6. 三AI同查窗口点击「思考档位」，分别选择三个模型的档位并保存，下次答题生效。

思考档位：GPT 低/中/高/更高/最高；千问 关闭/低/中/更高；DeepSeek V4.1 Flash 关闭/低/高/最高。
首次保持 GPT 中档、其余两家关闭；档位与密钥独立保存。更高思考通常更慢且用量更多。
追求响应速度可先用低档，再以实际题目评估正确率。

共享 API 配置由提供者明确授权打包，包含 GPT、千问、DeepSeek 密钥及各自接口地址的加密版本。
口令没有放在本 ZIP 中；请向提供者索取。只向获授权队友发送压缩包和口令。
共用密钥的 API 用量和费用计入提供者账号。导入会覆盖这三家的密钥和地址，原加密配置会备份。
每位队友应在自己的 Windows 账号下运行导入；程序会重新进行本机加密，之后不需要重复输入口令。
已保存的 API 密钥环境变量仍优先，若曾自行设置旧值，需要同时更新或清除。

升级保留原账号、成绩、刷题进度、错题本、自建题库和检测记录；不需要安装 Python 或 Node.js。
升级失败自动恢复，中断后再次双击同一入口继续恢复。备份在原工具箱 update-backups 内。
不要把本升级包解压到原工具箱中，也不要把已使用的工具箱目录再压缩发给队友。
原程序文件被手动修改时可能无法通过版本校验，请保留报错提示联系发布者。
'''
(target/'先读我_升级与共享API说明.txt').write_text(note,encoding='utf-8-sig')
archive=target.parent/(target.name+'.zip')
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as package:
    for file in sorted(target.rglob('*')):
        if file.is_file():package.write(file,Path(target.name)/file.relative_to(target))
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.zip.sha256.txt').write_text(digest+'  '+archive.name+'\n',encoding='utf-8')
print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':digest,'supportedBases':sorted(versions),'containsEncryptedSharedApi':True,'containsPassword':False},ensure_ascii=True))
