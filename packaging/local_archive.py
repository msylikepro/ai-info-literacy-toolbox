"""Local content-addressed ZIP backup. No network or credential processing."""
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import time
import zipfile

def digest(file):
    with file.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def safe_path(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value or value.startswith('/'):
        raise ValueError('Unsafe archive path')
    parts=value.split('/')
    if any(part in ('','.','..') or part.endswith((' ','.')) or any(ord(c)<32 for c in part)
           or re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',part,re.I) for part in parts):
        raise ValueError('Unsafe archive path')
    return PurePosixPath(value)

def snapshot(root,archive,excluded=None):
    root=Path(root).resolve();archive=Path(archive).resolve();excluded=set(excluded or ())
    if archive.exists():raise ValueError('Use a new archive filename')
    records=[];objects=set();directories=[];total=0;last=time.monotonic()
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=4,allowZip64=True) as package:
        for current,dirs,files in os.walk(root):
            base=Path(current)
            dirs[:]=sorted(d for d in dirs if (base/d).relative_to(root).parts[0] not in excluded)
            for name in dirs:
                folder=base/name
                if folder.is_symlink() or not folder.resolve().is_relative_to(root):raise ValueError('External link in backup')
                directories.append(folder.relative_to(root).as_posix())
            for name in sorted(files):
                file=base/name
                relative=file.relative_to(root).as_posix();safe_path(relative)
                if file==archive or relative.split('/')[0] in excluded:continue
                if file.is_symlink() or not file.resolve().is_relative_to(root):raise ValueError('External link in backup')
                before=file.stat();sha=digest(file)
                if sha not in objects:
                    package.write(file,'objects/'+sha);objects.add(sha)
                after=file.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise RuntimeError('File changed during backup: '+relative)
                records.append({'path':relative,'sha256':sha,'bytes':before.st_size,'mtimeNs':before.st_mtime_ns})
                total+=before.st_size
                if time.monotonic()-last>8:
                    print(json.dumps({'phase':'snapshot','files':len(records),'objects':len(objects),'sourceBytes':total}),flush=True);last=time.monotonic()
        manifest={'format':'toolbox-local-archive','version':1,'files':records,'directories':directories}
        package.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,separators=(',',':')))
    checksum=digest(archive)
    archive.with_suffix(archive.suffix+'.sha256.txt').write_text(checksum+'  '+archive.name+'\n',encoding='utf-8')
    return {'files':len(records),'objects':len(objects),'sourceBytes':total,'archiveBytes':archive.stat().st_size,'sha256':checksum}

def manifest_from(package):
    manifest=json.loads(package.read('manifest.json'))
    if manifest.get('format')!='toolbox-local-archive' or manifest.get('version')!=1:raise ValueError('Unknown archive format')
    seen=set()
    for item in manifest['files']:
        safe_path(item['path'])
        folded=item['path'].casefold()
        if folded in seen or not re.fullmatch('[0-9a-f]{64}',item['sha256']) or type(item['bytes']) is not int or item['bytes']<0:
            raise ValueError('Invalid archive record')
        seen.add(folded)
    for folder in manifest['directories']:safe_path(folder)
    return manifest

def verify(archive):
    checked=set();sizes={};last=time.monotonic()
    with zipfile.ZipFile(archive) as package:
        manifest=manifest_from(package)
        expected={item['sha256'] for item in manifest['files']}
        names=package.namelist()
        if len(names)!=len(set(names)) or set(names)!={'manifest.json',*('objects/'+sha for sha in expected)}:
            raise ValueError('Archive object list mismatch')
        for sha in sorted(expected):
            hasher=hashlib.sha256();size=0
            with package.open('objects/'+sha) as stream:
                while chunk:=stream.read(1024*1024):hasher.update(chunk);size+=len(chunk)
            if hasher.hexdigest()!=sha:raise ValueError('Archive content hash mismatch')
            checked.add(sha);sizes[sha]=size
            if time.monotonic()-last>8:
                print(json.dumps({'phase':'verify','objects':len(checked),'total':len(expected)}),flush=True);last=time.monotonic()
        if any(item['bytes']!=sizes[item['sha256']] for item in manifest['files']):raise ValueError('Archive file size mismatch')
    return {'passed':True,'files':len(manifest['files']),'objects':len(checked),'sourceBytes':sum(item['bytes'] for item in manifest['files'])}

def restore(archive,destination):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Restore destination must not already exist')
    verify(archive)
    with zipfile.ZipFile(archive) as package:
        manifest=manifest_from(package);destination.mkdir(parents=True)
        for relative in manifest['directories']:(destination/str(safe_path(relative))).mkdir(parents=True,exist_ok=True)
        for item in manifest['files']:
            file=destination/str(safe_path(item['path']));file.parent.mkdir(parents=True,exist_ok=True)
            with package.open('objects/'+item['sha256']) as source,file.open('xb') as output:
                while chunk:=source.read(1024*1024):output.write(chunk)
            os.utime(file,ns=(item['mtimeNs'],item['mtimeNs']))
    return {'restoredFiles':len(manifest['files']),'destination':str(destination)}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('snapshot','verify','restore'))
    parser.add_argument('archive',type=Path);parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--exclude',nargs='*',default=['归档管理']);parser.add_argument('--destination',type=Path)
    args=parser.parse_args()
    if args.action=='snapshot':result=snapshot(args.root,args.archive,args.exclude)
    elif args.action=='verify':result=verify(args.archive)
    else:
        if args.destination is None:parser.error('restore requires --destination')
        result=restore(args.archive,args.destination)
    print(json.dumps(result,ensure_ascii=True),flush=True)
