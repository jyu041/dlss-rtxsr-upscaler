"""Assemble the portable Python and FFmpeg runtimes from verified pinned inputs."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, urllib.request, zipfile
from pathlib import Path

def digest(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest().upper()

def safe_extract(z: zipfile.ZipFile, dest: Path, selected=None):
    names = [i.filename for i in z.infolist() if selected is None or i.filename in selected]
    for n in names:
        q = (dest / n).resolve()
        if not str(q).startswith(str(dest.resolve()) + os.sep): raise RuntimeError(f'unsafe archive member: {n}')
        if n.endswith('/'):
            q.mkdir(parents=True, exist_ok=True); continue
        q.parent.mkdir(parents=True, exist_ok=True)
        with z.open(n) as src, q.open('wb') as out: shutil.copyfileobj(src, out)

def fetch(url: str, path: Path, expected: str):
    if not url.lower().startswith('https://'): raise RuntimeError(f'non-HTTPS source refused: {url}')
    if path.is_file() and digest(path) == expected: return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.part')
    if tmp.exists(): tmp.unlink()
    urllib.request.urlretrieve(url, tmp)
    if digest(tmp) != expected: tmp.unlink(); raise RuntimeError(f'hash mismatch: {path.name}')
    tmp.replace(path)

def assemble(root: Path, python_archive: Path, ffmpeg_archive: Path, wheel_dir: Path, lock: Path, python_only=False, ffmpeg_only=False, runtime_root: Path | None = None):
    data=json.loads(lock.read_text(encoding='utf-8')); arts=data['artifacts']
    if not arts: raise RuntimeError('empty artifact lock')
    runtime_root = (runtime_root or root/'runtime').resolve()
    py=runtime_root/'python'; ff=runtime_root/'tools'/'ffmpeg'
    if not ffmpeg_only:
        if py.exists():
            shutil.rmtree(py, ignore_errors=True)
            if py.exists(): raise RuntimeError(f'could not remove existing Python runtime: {py}')
        py.mkdir(parents=True)
        with zipfile.ZipFile(python_archive) as z: safe_extract(z, py)
        site=py/'Lib'/'site-packages'; site.mkdir(parents=True, exist_ok=True)
        for a in arts: fetch(a['url'], wheel_dir/a['filename'], a['sha256'])
        pipwheel=next((a for a in arts if a['name']=='pip'), None)
        if not pipwheel: raise RuntimeError('lock does not contain pip bootstrap')
        with zipfile.ZipFile(wheel_dir/pipwheel['filename']) as z: safe_extract(z, site)
        req=runtime_root/'locked-requirements.txt'
        req.write_text('\n'.join(f"{a['name']}=={a['version']} --hash=sha256:{a['sha256']}" for a in arts if a['name']!='pip')+'\n', encoding='utf-8', newline='\n')
        pyexe=py/'python.exe'
        subprocess.run([str(pyexe),'-m','pip','install','--no-index','--find-links',str(wheel_dir),'--no-deps','--require-hashes','--target',str(site),'-r',str(req)], check=True)
        req.unlink()
    with zipfile.ZipFile(ffmpeg_archive) as z:
        members={i.filename for i in z.infolist()}
        matches={n for n in members if n.endswith('/bin/ffmpeg.exe') or n.endswith('/bin/ffprobe.exe')}
        if len(matches)!=2: raise RuntimeError(f'expected two FFmpeg executables, found {sorted(matches)}')
        for n in matches: safe_extract(z, ff, {n}); (ff/Path(n).name).write_bytes((ff/n).read_bytes()); (ff/n).unlink()
    return {'python': str(py/'python.exe'), 'ffmpeg': str(ff/'ffmpeg.exe'), 'ffprobe': str(ff/'ffprobe.exe'), 'artifacts': len(arts)}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); p.add_argument('--runtime-root',type=Path); p.add_argument('--python-archive',type=Path,required=True); p.add_argument('--ffmpeg-archive',type=Path,required=True); p.add_argument('--wheel-dir',type=Path,required=True); p.add_argument('--lock',type=Path,required=True)
    p.add_argument('--python-only', action='store_true'); p.add_argument('--ffmpeg-only', action='store_true'); a=p.parse_args(); print(json.dumps(assemble(a.root.resolve(),a.python_archive.resolve(),a.ffmpeg_archive.resolve(),a.wheel_dir.resolve(),a.lock.resolve(), a.python_only, a.ffmpeg_only, a.runtime_root),indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
