"""Build and verify v1.9 deltas without altering shipped releases or user data."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
DELIVERY=ROOT/'交付文件'
EVIDENCE=ROOT/'00_整理记录/自定义答题时间验证_2026-10-17'
VERSIONS=('1.0.0','1.1.0','1.2.0','1.3.0','1.4.0','1.4.1','1.5.0','1.6.0','1.7.0','1.8.0')
def old_folder(version):return DELIVERY/('AI信息素养工具箱_Windows免安装版'+('' if version=='1.0.0' else '_v'+version))
def patch_folder(version):return DELIVERY/('AI信息素养工具箱_离线升级包_v'+version+'到v1.9.0')
def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('build','verify'))
    parser.add_argument('--versions',nargs='+',choices=VERSIONS,default=VERSIONS);parser.add_argument('--label',default='')
    args=parser.parse_args();EVIDENCE.mkdir(parents=True,exist_ok=True)
    def run(version):
        if args.mode=='build':
            command=[sys.executable,str(ROOT/'packaging/build_update.py'),'--base',str(old_folder(version)),
                     '--new',str(DELIVERY/'AI信息素养工具箱_Windows免安装版_v1.9.0'),'--output',str(patch_folder(version))]
        else:
            command=[sys.executable,str(ROOT/'packaging/verify_offline_update.py'),'--old',str(old_folder(version))+'.zip',
                     '--update',str(patch_folder(version)),'--destination',str(EVIDENCE/('旧版升级验收_'+version+args.label))]
        result=subprocess.run(command,capture_output=True,encoding='utf-8',errors='replace',timeout=300)
        (EVIDENCE/(args.mode+'_'+version+args.label+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode:raise RuntimeError(version+': '+result.stdout[-2000:]+result.stderr[-4000:])
        return {'version':version,'passed':True,'output':result.stdout[-1800:]}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(run,version) for version in args.versions]):
            print(json.dumps(future.result(),ensure_ascii=True),flush=True)
if __name__=='__main__':main()
