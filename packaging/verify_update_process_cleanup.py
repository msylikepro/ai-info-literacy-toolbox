"""Terminate a host running the actual updater validation method; child must stop."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('--updater',type=Path,required=True)
    parser.add_argument('--python',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();folder=args.destination.resolve();folder.mkdir(parents=True,exist_ok=True)
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    host=folder/'UpdateChildCheck.exe'
    subprocess.run([str(compiler),'/nologo','/target:exe','/platform:x64','/out:'+str(host),
                    str(Path(__file__).parent/'tests/UpdateChildCheck.cs')],check=True)
    helper=folder/'slow-validation.py'
    helper.write_text("import os,sys,time\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(str(os.getpid()))\ntime.sleep(90)\n",encoding='utf-8')
    pid_file=folder/'validation-child.pid'
    if pid_file.exists():pid_file.unlink()
    # Materializing os.environ also normalizes duplicate Windows Path/PATH keys
    # inherited from some process orchestrators before .NET reads the block.
    process=subprocess.Popen([str(host),str(args.updater.resolve()),str(args.python.resolve()),str(helper),str(pid_file),str(folder),str(folder/'child.log')],
                             env=dict(os.environ),creationflags=subprocess.CREATE_NO_WINDOW)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT];kernel.TerminateProcess.restype=wintypes.BOOL
    child=None;handle=None
    try:
        deadline=time.monotonic()+15
        while not pid_file.exists() and time.monotonic()<deadline:
            if process.poll() is not None:
                error=folder/'host-error.log'
                raise AssertionError(error.read_text(encoding='utf-8-sig') if error.exists() else 'Validation host exited before child started')
            time.sleep(.05)
        assert pid_file.exists(),'Validation child did not start'
        child=int(pid_file.read_text());handle=kernel.OpenProcess(0x00100001,False,child)
        assert handle,'Validation child was not running'
        process.kill();process.wait(timeout=5)
        stopped=kernel.WaitForSingleObject(handle,3000)==0
        assert stopped,'Validation child survived abrupt updater termination'
        result={'passed':True,'validationChildStoppedOnUpdaterTermination':True}
        (folder/'验证进程清理结果.json').write_text(json.dumps(result),encoding='utf-8');print(json.dumps(result))
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)
        if handle:
            if kernel.WaitForSingleObject(handle,0)!=0:
                if not kernel.TerminateProcess(handle,1):raise ctypes.WinError(ctypes.get_last_error())
                assert kernel.WaitForSingleObject(handle,5000)==0,'Test child cleanup did not finish'
            kernel.CloseHandle(handle)


if __name__=='__main__':main()
