"""Wrap verified version-specific native updates behind one offline chooser."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

here=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument('--output',required=True,type=Path)
parser.add_argument('--updates',required=True,nargs='+',type=Path)
args=parser.parse_args()
target=args.output.resolve()
if target.exists():raise SystemExit('Use a new output folder')
descriptions=[json.loads((folder/'升级清单.json').read_text(encoding='utf-8')) for folder in args.updates]
versions={item['fromVersion'] for item in descriptions}
targets={item['toVersion'] for item in descriptions}
assert versions=={'1.0.0','1.1.0','1.2.0','1.3.0','1.4.0','1.4.1','1.5.0','1.6.0','1.7.0','1.8.0','1.9.0'} and len(targets)==1
version=targets.pop()
script=(here/'StartOfflineUpgrade.ps1').read_text(encoding='utf-8-sig')
assert "TargetVersion='"+version+"'" in script,'The chooser target does not match the native updates'
target.mkdir(parents=True)
for folder,item in zip(args.updates,descriptions):
    destination=target/'updates'/item['fromVersion'];destination.mkdir(parents=True)
    for name in ('双击升级.exe','升级清单.json','升级说明.txt'):shutil.copy2(folder/name,destination/name)
shutil.copy2(here/'StartOfflineUpgrade.ps1',target/'offline_upgrade.ps1')
(target/'双击开始升级.bat').write_bytes(b'@echo off\r\nstart "" powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0offline_upgrade.ps1"\r\n')
note=f'''AI＋信息素养工具箱 · 离线升级至 v{version}

1. 关闭原工具箱，将本 ZIP 完整解压到原工具箱文件夹之外。
2. 双击「双击开始升级.bat」，选择原 AI信息素养工具箱.exe 所在的文件夹。
3. 程序自动识别最初版本及 v1.1.0 至 v1.9.0 的正式发行版，打开对应升级窗口。
4. 点击「开始升级」，成功后仍从原文件夹打开工具箱。

本次更新：
题库蒸馏：将原373题整理为229道有效题，合并已核对的格式重复与同义重复。
新刷题轮、题库浏览及模考抽题使用有效题；历史题目、成绩、错题和收藏保留。
未完成刷题轮只移除尚未作答且无草稿的重复项，保留已答、当前题与草稿断点。
新导入会识别已核对的重复版本，未知近似题保留，避免误合并检索符号或代码原文。
答案冲突保留原始资料并提示核验。

同时包含此前更新：
答题时间支持自定义。个人练习、团队练习、个人对抗、团队对抗和完整模拟总时限均可分别保存。
按整数分钟填写，0表示不限时，最大1440分钟；修改只用于新开试卷，已开始的试卷和模拟固定原时限。
完整模拟的各阶段时限仍受本场总时限约束；总时限设0时不受总截止时间约束。

同时包含此前更新：
个人和团队模式支持自定义题数与计分。
在模考控制台展开「出题与计分设置」，分别设置个人和团队的单选、多选、判断题数，
以及每类题答对、答错、未作答的分值，点击保存后开始。
每卷至少1题、最多500题，可将某类题设为0；题库不足时会提示，不会少出或重复出题。
分值支持负数、零和最多两位小数；答对得分不为负，答错或未答得分不高于答对得分。
练习、对抗与完整模拟均采用相应设置；团队和完整模拟以发起者保存的规则为准。
设置按本机登录账号保存；已开始及历史试卷保留开卷时的规则，不会跟随修改。
总分、逐题得分、历史成绩和模拟总分同步按本卷规则显示，时限使用已保存的时间设置。

同时包含之前的更新：
一、三 AI 同查支持上传或粘贴题目截图，三个模型分别识别并作答。
   点击「上传图片」或「粘贴图片」，可以只发图片，也可附加文字；「移除图片」可取消附件。
   支持 PNG、JPEG；粘贴图片自动转为 PNG，单张最多 10 MB、单边不超过 8192 像素。
   AI 提问需要联网，接口必须支持图片输入；保留现有模型、API 地址、密钥和思考设置。
二、知识点资料新增「AI 知数」，更新国家药品监督管理局数据查询系统的网址。
三、知识点资料支持「添加网址」，填写网址名称及网址后保存；每条现有或新增资料均可「修改」。
   从工具箱的「知识点资料」进入即可操作，保存后重开仍保留，也能参与搜索和网站检测。
   修改名称保留检测记录；修改网址会归档旧检测与审核信息，新网址需要重新检测和审核。

同时保留题库浏览、刷题断点、错题本、收藏集、模考及之前的修复。
现有 API 配置、账号、成绩、刷题进度、错题、收藏和无关网址的审核记录均保留。
本升级包不重新导入或更换密钥；已配置的 API 无需重填。
升级不需要联网、管理员权限或安装 Python、Node.js。
原程序文件被修改、版本不匹配或工具箱仍在运行时，升级程序会给出提示。
升级失败自动恢复，中途断电或关闭后重新运行同一入口恢复。
备份在原工具箱的 update-backups 中，包含个人数据，请勿转发。
'''
(target/'先读我_升级说明.txt').write_text(note,encoding='utf-8-sig')
archive=target.parent/(target.name+'.zip')
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as package:
    for file in sorted(target.rglob('*')):
        if file.is_file():package.write(file,Path(target.name)/file.relative_to(target))
checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.zip.sha256.txt').write_text(checksum+'  '+archive.name+'\n',encoding='utf-8')
print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':checksum,'targetVersion':version,'sourceVersions':sorted(versions)},ensure_ascii=True))
